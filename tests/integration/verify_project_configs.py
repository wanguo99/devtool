"""Read-only smoke of the packaged engine with the three existing project configs."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import tempfile


ROOT=Path(__file__).resolve().parents[2]


def run(argv,cwd,env=None):
    return subprocess.check_output([str(value) for value in argv],cwd=cwd,env=env,text=True,stderr=subprocess.DEVNULL)


def status(repo):
    return run(['git','status','--porcelain=v1'],repo)


def verify(binary, name, repo, plan_args):
    before=status(repo)
    with tempfile.TemporaryDirectory(prefix='devtool-project-config-') as directory:
        view=Path(directory)
        shutil.copy2(binary,view/'devtool')
        shutil.copy2(ROOT/'examples/projects'/name/'devtool.toml',view/'devtool.toml')
        # Only expose the existing backend implementation; no business files or
        # deployment credentials are copied and no original root launcher is used.
        (view/'tools').symlink_to(repo/'tools',target_is_directory=True)
        env={**os.environ,'DEVTOOL_STATE_HOME':str(view/'state'),'PYTHONDONTWRITEBYTECODE':'1'}
        executor=view/'devtool'
        task_list=json.loads(run([executor,'validate'],view,env))
        result=json.loads(run([executor,'legacy-help','--json'],view,env))
        if result['status']!='SUCCEEDED':raise RuntimeError(f'{name}: backend help failed')
        if plan_args:
            result=json.loads(run([executor,'legacy-plan','--json','--',*plan_args],view,env))
            if result['status']!='SUCCEEDED':raise RuntimeError(f'{name}: backend plan failed')
        if status(repo)!=before:raise RuntimeError(f'{name}: original checkout status changed')
        print(f'{name}: {len(task_list["tasks"])} configured tasks; binary/backend read-only smoke passed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,required=True)
    for name in ('smart-alarm','zippos','ntn-workspace'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    verify(args.binary.resolve(),'smart-alarm',args.smart_alarm.resolve(),None)
    verify(args.binary.resolve(),'zippos',args.zippos.resolve(),['build','all'])
    verify(args.binary.resolve(),'ntn-workspace',args.ntn_workspace.resolve(),['build','all','--platform','phytium'])


if __name__=='__main__':main()
