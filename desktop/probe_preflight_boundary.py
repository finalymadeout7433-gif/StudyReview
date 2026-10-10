"""Five targeted synthetic path regressions with measured read/connect counts."""
from pathlib import Path
import json,unittest
import MySQLdb
from desktop.test_preflight import PreflightTests

class ObservedPreflightTests(PreflightTests):
    def run_check(self,**options):
        report=super().run_check(**options)
        self.observation={
            'configuration_read_calls':Path.read_text.call_count,
            'database_connect_calls':MySQLdb.connect.call_count,
            'configured':report['configured'],
            'database_checked':report['database_checked'],
            'ready_to_launch':report['ready_to_launch'],
            'private_path_rejected':not next(c['passed']for c in report['checks']if c['code']=='private_path_boundary'),
        }
        return report

class ObservedResult(unittest.TextTestResult):
    def addSuccess(self,test):
        super().addSuccess(test)
        observations.append({'test':test.id(),**test.observation})

names=(
    'test_private_junction_refused_before_any_config_read_or_connection',
    'test_private_junction_refused_also_in_path_only_diagnose',
    'test_runtime_json_redirect_refused_even_with_explicit_credentials',
    'test_development_json_redirect_refused_before_credential_reads',
    'test_private_path_resolution_error_redacted_without_reads_or_connection',
)
observations=[]
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2,resultclass=ObservedResult).run(unittest.TestSuite(ObservedPreflightTests(name)for name in names))
    success=result.wasSuccessful()and len(observations)==5 and all(item['configuration_read_calls']==0 and item['database_connect_calls']==0 and item['private_path_rejected']and not item['ready_to_launch']and not item['configured']and not item['database_checked']for item in observations)
    Path('desktop/evidence/phase6-preflight-zero-io.json').write_text(json.dumps({'success':success,'cases':observations,'real_junction_created':False,'real_private_config_read':False,'real_database_connected':False},ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if success else 1)
