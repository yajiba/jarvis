"""Persistent, explicitly approved automation with atomic job claiming."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3

from jarvis.tools.registry import Tool


def utcnow():
    return datetime.now(timezone.utc)


def due_time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('Use an ISO-8601 time with a timezone offset') from error
    if result.tzinfo is None:
        raise ValueError('A timezone offset is required, for example +08:00')
    return result.astimezone(timezone.utc)


def parameters(**fields):
    return {'type': 'object', 'properties': {name: {'type': 'string', **spec}
            for name, spec in fields.items()}, 'required': list(fields), 'additionalProperties': False}


class Automation:
    def __init__(self, path: Path, projects, notify=None):
        self.path = path
        self.projects = projects
        self.notify = notify or (lambda event: None)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS automation_jobs (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, due_at TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open', last_result TEXT, last_state TEXT);
                CREATE TABLE IF NOT EXISTS automation_events (
                    id INTEGER PRIMARY KEY, job_id INTEGER, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, result TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def command_preview(self, title, project, command, due_at, recurrence):
        if not title.strip() or len(title) > 500:
            raise ValueError('Title must contain 1 to 500 characters')
        due = due_time(due_at)
        if recurrence not in {'none', 'daily', 'weekly'}:
            raise ValueError('Recurrence must be none, daily, or weekly')
        return {**self.projects.preview(project, command), 'title': title,
                'due_at': due.isoformat(), 'recurrence': recurrence,
                'authorization': 'Run this exact configured command unattended at these times while Jean is running. Changed command configuration blocks execution.'}

    def schedule_command(self, title, project, command, due_at, recurrence):
        preview = self.command_preview(title, project, command, due_at, recurrence)
        payload = {key: preview[key] for key in ('project', 'command', 'directory', 'argv')}
        return self.add(title, 'command', payload, due_time(due_at),
                        {'none': 0, 'daily': 86400, 'weekly': 604800}[recurrence])

    def monitor_service(self, title, port, interval_seconds):
        port, interval = int(port), int(interval_seconds)
        if not 1 <= port <= 65535 or not 10 <= interval <= 86400:
            raise ValueError('Port must be 1-65535; interval must be 10-86400 seconds')
        return self.add(title, 'service', {'port': port}, utcnow(), interval)

    def add(self, title, kind, payload, due, interval):
        if not title.strip() or len(title) > 500:
            raise ValueError('Title must contain 1 to 500 characters')
        with self.connect() as db:
            cursor = db.execute('INSERT INTO automation_jobs(title,kind,payload,due_at,interval_seconds) VALUES(?,?,?,?,?)',
                                (title, kind, json.dumps(payload), due.isoformat(), interval))
            return {'id': cursor.lastrowid, 'status': 'open', 'due_at': due.isoformat()}

    def list_jobs(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,title,kind,due_at,interval_seconds,status,last_result FROM automation_jobs ORDER BY id DESC LIMIT 200')]

    def events(self):
        with self.connect() as db:
            return [{**dict(row), 'result': json.loads(row['result'])} for row in db.execute(
                'SELECT * FROM automation_events ORDER BY id DESC LIMIT 100')]

    def cancel(self, job_id):
        with self.connect() as db:
            row = db.execute("UPDATE automation_jobs SET status='cancelled' WHERE id=? AND status IN ('open','running','failed')", (int(job_id),))
            if not row.rowcount:
                raise ValueError('No cancellable job with that id')
        return 'Cancelled future runs; an already running command is not terminated'

    def _execute(self, job):
        payload = json.loads(job['payload'])
        if job['kind'] == 'command':
            current = self.projects.preview(payload['project'], payload['command'])
            if any(current[key] != payload[key] for key in ('project', 'command', 'directory', 'argv')):
                raise ValueError('Approved command configuration changed; cancel and schedule again')
            result = self.projects.run_command(payload['project'], payload['command'])
            if result.get('timed_out') or result.get('exit_code') != 0:
                return {'ok': False, 'result': result}, None
            return {'ok': True, 'result': result}, None
        if job['kind'] != 'service':
            raise ValueError('Unknown automation kind')
        try:
            with socket.create_connection(('127.0.0.1', payload['port']), timeout=2):
                state = 'up'
        except OSError:
            state = 'down'
        return {'ok': True, 'state': state, 'port': payload['port'],
                'note': 'TCP reachability only; not an application health check'}, state

    def run_due_once(self):
        now = utcnow()
        with self.connect() as db:
            jobs = [dict(row) for row in db.execute(
                "SELECT * FROM automation_jobs WHERE status='open' AND due_at<=? ORDER BY due_at LIMIT 20", (now.isoformat(),))]
        count = 0
        for job in jobs:
            with self.connect() as db:
                if not db.execute("UPDATE automation_jobs SET status='running' WHERE id=? AND status='open' AND due_at=?",
                                  (job['id'], job['due_at'])).rowcount:
                    continue
            try:
                result, state = self._execute(job)
            except Exception as error:
                result, state = {'ok': False, 'error': str(error)}, None
            interval = job['interval_seconds']
            next_due = due_time(job['due_at'])
            if interval:
                # Skip missed intervals instead of replaying a backlog of actions.
                elapsed = max(0, (utcnow() - next_due).total_seconds())
                next_due += timedelta(seconds=(int(elapsed // interval) + 1) * interval)
            status = ('open' if interval else 'completed') if result['ok'] else 'failed'
            should_notify = job['kind'] != 'service' or state != job['last_state'] or not result['ok']
            event = {'job_id': job['id'], 'title': job['title'], 'result': result}
            with self.connect() as db:
                db.execute("UPDATE automation_jobs SET status=CASE WHEN status='cancelled' THEN status ELSE ? END,due_at=?,last_result=?,last_state=? WHERE id=?",
                           (status, next_due.isoformat(), json.dumps(result), state, job['id']))
                if should_notify:
                    db.execute('INSERT INTO automation_events(job_id,title,created_at,result) VALUES(?,?,?,?)',
                               (job['id'], job['title'], utcnow().isoformat(), json.dumps(result)))
                    db.execute('DELETE FROM automation_events WHERE id NOT IN (SELECT id FROM automation_events ORDER BY id DESC LIMIT 1000)')
            if should_notify:
                try:
                    self.notify(event)
                except Exception:
                    pass  # The durable event remains available even if notification fails.
            count += 1
        return count

    def tools(self):
        return [
            Tool('schedule_project_command', 'Schedule an approved project command. Approval authorizes unattended runs of this exact command.',
                 parameters(title={}, project={}, command={}, due_at={}, recurrence={'enum': ['none','daily','weekly']}),
                 self.schedule_command, 'confirm', self.command_preview),
            Tool('monitor_service', 'Monitor a local TCP service on 127.0.0.1 and notify on state changes. Does not restart it.',
                 parameters(title={}, port={}, interval_seconds={}), self.monitor_service, 'confirm'),
            Tool('list_automations', 'List persistent automation jobs, status, and last results.', parameters(), self.list_jobs),
            Tool('automation_events', 'Read recent scheduled action results and service alerts.', parameters(), self.events),
            Tool('cancel_automation', 'Cancel future runs of an automation by id.', parameters(job_id={}), self.cancel, 'confirm'),
        ]
