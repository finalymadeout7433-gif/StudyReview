"""Owned native GUI only; no save/credential values/DB writes/provider calls."""
import argparse,json
from pathlib import Path
from desktop.setup_wizard import run_wizard
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--readonly-check',action='store_true');parser.add_argument('--settings',default='config.settings');args=parser.parse_args()
    output=Path(args.output);report={'checks':[],'saved_configuration':False,'real_ai_called':False}
    def check(name,value):report['checks'].append({'name':name,'passed':bool(value)})
    def shown(form,controls):
        from System.Drawing import Bitmap
        from System.Drawing.Imaging import ImageFormat
        from System.Windows.Forms import Timer,TextRenderer
        check('native_owned_form_created',form.IsHandleCreated)
        check('save_confirmation_initially_unchecked',not controls['confirm'].Checked)
        check('replace_confirmation_initially_unchecked',not controls['replace'].Checked)
        check('save_initially_disabled',not controls['save'].Enabled)
        check('launch_initially_disabled',not controls['launch'].Enabled)
        check('paths_only_no_password_control',all(not getattr(item,'UseSystemPasswordChar',False)for item in form.Controls))
        check('controls_within_client',all(item.Left>=0 and item.Top>=0 and item.Right<=form.ClientSize.Width and item.Bottom<=form.ClientSize.Height for item in form.Controls))
        timer=Timer();timer.Interval=150;elapsed={'count':0}
        def finish(sender,event):
            elapsed['count']+=1
            if args.readonly_check and controls['check'].Enabled and elapsed['count']>2 and controls['launch'].Enabled:
                check('readonly_check_enables_launch',True)
            elif elapsed['count']<30:return
            elif args.readonly_check:check('readonly_check_enables_launch',False)
            check('checking_did_not_auto_check_consent',not controls['confirm'].Checked)
            check('checking_did_not_auto_enable_save',not controls['save'].Enabled)
            bitmap=Bitmap(form.Width,form.Height)
            from System.Drawing import Rectangle
            form.DrawToBitmap(bitmap,Rectangle(0,0,form.Width,form.Height));bitmap.Save(str(output.with_suffix('.png')),ImageFormat.Png);bitmap.Dispose()
            report['native_size']=[form.Width,form.Height];timer.Stop();form.Close();timer.Dispose()
        timer.Tick+=finish;timer.Start();report['_timer']=timer
        if args.readonly_check:controls['check'].PerformClick()
    selection=run_wizard(Path(__file__).resolve().parent.parent,args.data_dir,settings_module=args.settings,on_shown=shown)
    report.pop('_timer',None);check('probe_closed_without_launch_or_save',selection is None)
    report['success']=all(row['passed']for row in report['checks'])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'success':report['success'],'checks':len(report['checks']),'output':str(output)}));return 0 if report['success']else 1
if __name__=='__main__':raise SystemExit(main())
