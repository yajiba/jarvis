from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from jarvis.scheduler.automation import Automation, due_time, utcnow
from jarvis.tools.registry import ToolRegistry


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.projects = Mock()
        self.projects.preview.return_value = {'project':'demo','command':'check','directory':'/demo','argv':['python','check.py']}
        self.projects.run_command.return_value = {'exit_code':0,'timed_out':False}
        self.events = []
        self.engine = Automation(Path(self.temp.name)/'automation.db', self.projects, self.events.append)
        self.args = dict(title='Check project',project='demo',command='check',
                         due_at=(utcnow()-timedelta(days=9)).isoformat(),recurrence='none')

    def test_denied_schedule_does_not_persist_or_execute(self):
        result = ToolRegistry(self.engine.tools()).execute('schedule_project_command',self.args)
        self.assertFalse(result['ok'])
        self.assertEqual(self.engine.list_jobs(),[])
        self.projects.run_command.assert_not_called()

    def test_approved_job_survives_restart_runs_once_and_records_result(self):
        approvals=[]
        registry=ToolRegistry(self.engine.tools(),lambda name,details: approvals.append(details) or True)
        self.assertTrue(registry.execute('schedule_project_command',self.args)['ok'])
        self.assertEqual(approvals[0]['argv'],['python','check.py'])
        restarted=Automation(self.engine.path,self.projects)
        self.assertEqual(restarted.run_due_once(),1)
        self.assertEqual(self.engine.run_due_once(),0)
        self.projects.run_command.assert_called_once_with('demo','check')
        self.assertEqual(restarted.events()[0]['result']['ok'],True)

    def test_configuration_change_blocks_command_and_stops_recurrence(self):
        self.engine.schedule_command(**{**self.args,'recurrence':'daily'})
        self.projects.preview.return_value={**self.projects.preview.return_value,'argv':['python','different.py']}
        self.engine.run_due_once()
        self.projects.run_command.assert_not_called()
        self.assertEqual(self.engine.list_jobs()[0]['status'],'failed')

    def test_missed_recurrences_do_not_replay_backlog(self):
        self.engine.schedule_command(**{**self.args,'recurrence':'daily'})
        self.engine.run_due_once()
        self.assertGreater(due_time(self.engine.list_jobs()[0]['due_at']),utcnow())
        self.assertEqual(self.engine.run_due_once(),0)

    def test_two_workers_claim_only_once(self):
        self.engine.schedule_command(**self.args)
        other=Automation(self.engine.path,self.projects)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda engine: engine.run_due_once(),[self.engine,other]))
        self.assertEqual(sum(results),1)
        self.projects.run_command.assert_called_once()

    def test_cancelled_running_job_is_not_rescheduled(self):
        job=self.engine.schedule_command(**{**self.args,'recurrence':'daily'})
        def command(*args):
            self.engine.cancel(str(job['id']))
            return {'exit_code':0}
        self.projects.run_command.side_effect=command
        self.engine.run_due_once()
        self.assertEqual(self.engine.list_jobs()[0]['status'],'cancelled')

    def test_monitor_alerts_only_on_state_changes(self):
        self.engine.monitor_service('Local API','8765','10')
        with patch('jarvis.scheduler.automation.socket.create_connection',side_effect=OSError('down')):
            self.engine.run_due_once()
            with self.engine.connect() as db:
                db.execute("UPDATE automation_jobs SET due_at=?",(self.args['due_at'],))
            self.engine.run_due_once()
        self.assertEqual(len(self.events),1)
        self.assertEqual(self.events[0]['result']['state'],'down')
        with self.engine.connect() as db:
            db.execute("UPDATE automation_jobs SET due_at=?",(self.args['due_at'],))
        with patch('jarvis.scheduler.automation.socket.create_connection') as connect:
            self.engine.run_due_once()
            connect.assert_called_once_with(('127.0.0.1',8765),timeout=2)
        self.assertEqual(self.events[-1]['result']['state'],'up')

    def test_failed_command_does_not_prevent_other_jobs(self):
        self.engine.schedule_command(**self.args)
        self.engine.schedule_command(**self.args)
        self.projects.run_command.side_effect=[RuntimeError('failed'),{'exit_code':0}]
        self.assertEqual(self.engine.run_due_once(),2)
        self.assertEqual({job['status'] for job in self.engine.list_jobs()},{'completed','failed'})

    def test_timezone_and_monitor_limits(self):
        with self.assertRaises(ValueError):
            due_time('2026-09-15T08:00:00')
        with self.assertRaises(ValueError):
            self.engine.monitor_service('bad','99999','10')
        with self.assertRaises(ValueError):
            self.engine.monitor_service('bad','80','0')
