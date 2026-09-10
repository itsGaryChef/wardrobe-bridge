"""Run with ordinary Python 3.10+: python mcp_server.py --bridge-dir PATH.

Standard newline-delimited MCP stdio, no Blender or third-party Python imports.
The Blender add-on must have its local agent connection enabled.
"""
import argparse
import base64
import concurrent.futures
import json
import pathlib
import sys
import threading
import time
import uuid
from protocol import TOOLS,validate_call

def main():
    # Windows consoles otherwise default to a legacy codepage, breaking avatar names.
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--bridge-dir',required=True);parser.add_argument('--timeout',type=float,default=240)
    options=parser.parse_args();root=pathlib.Path(options.bridge_dir).expanduser().resolve()
    output_lock=threading.Lock();pending_lock=threading.Lock();pending={};initialized=False
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    def send(value):
        with output_lock:sys.stdout.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');sys.stdout.flush()
    def reply(key,value):send({'jsonrpc':'2.0','id':key,'result':value})
    def error(key,code,message):send({'jsonrpc':'2.0','id':key,'error':{'code':code,'message':message}})
    def call(key,name,args,cancel):
        request_id=uuid.uuid4().hex;request=root/f'request-{request_id}.json';response=root/f'response-{request_id}.json'
        try:
            validate_call(name,args)
            status=json.loads((root/'session.json').read_text(encoding='utf-8'))
            if not status.get('active') or time.time()-status.get('heartbeat',0)>300:raise ValueError('Enable the Wardrobe agent connection in Blender first.')
            if cancel.is_set():raise ValueError('Cancelled before execution.')
            deadline=time.time()+options.timeout
            value={'session':status['session'],'tool':name,'arguments':args,'deadline':deadline}
            temp=request.with_suffix('.tmp');temp.write_text(json.dumps(value),encoding='utf-8');temp.replace(request)
            while not response.exists():
                if cancel.is_set() or time.time()>deadline:
                    (root/f'cancel-{request_id}.json').write_text('{}',encoding='utf-8')
                    request.unlink(missing_ok=True)
                    raise ValueError('Request cancelled or timed out. If Blender had started it, inspect the scene before retrying; an in-progress operation cannot be interrupted.')
                time.sleep(.05)
            result=json.loads(response.read_text(encoding='utf-8'));response.unlink(missing_ok=True)
            if not result['ok']:raise ValueError(result['error'])
            payload=result['result'];content=[{'type':'text','text':json.dumps(payload,ensure_ascii=False)}]
            if name=='wardrobe_preview':
                path=pathlib.Path(payload['path'])
                content.append({'type':'image','mimeType':'image/png','data':base64.b64encode(path.read_bytes()).decode('ascii')})
            reply(key,{'content':content,'structuredContent':payload,'isError':False})
        except Exception as exc:reply(key,{'content':[{'type':'text','text':str(exc)}],'isError':True})
        finally:
            with pending_lock:pending.pop(key,None)
    try:
        for line in sys.stdin:
            key=None
            try:
                if len(line)>1000000:raise ValueError('Request too large.')
                message=json.loads(line);key=message.get('id');method=message.get('method');params=message.get('params',{})
                if message.get('jsonrpc')!='2.0':raise ValueError('Expected JSON-RPC 2.0.')
                if method=='initialize':
                    initialized=True;requested=params.get('protocolVersion')
                    version=requested if requested in {'2024-11-05','2025-03-26','2025-06-18'} else '2025-06-18'
                    reply(key,{'protocolVersion':version,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'wardrobe-bridge','version':'0.4.0'},'instructions':'Inspect the scene and render fits. Preserve original avatars. Fits require visual review. Use regional revision tools and do not repeat a timed-out mutation without checking the scene.'})
                elif method=='notifications/cancelled':
                    with pending_lock:
                        event=pending.get(params.get('requestId'))
                        if event:event.set()
                elif key is None:continue
                elif method=='ping':reply(key,{})
                elif not initialized:error(key,-32002,'Initialize first.')
                elif method=='tools/list':reply(key,{'tools':TOOLS})
                elif method=='tools/call':
                    validate_call(params.get('name'),params.get('arguments',{}))
                    with pending_lock:
                        if key in pending:raise ValueError('Duplicate request id.')
                        event=threading.Event();pending[key]=event
                    pool.submit(call,key,params['name'],params.get('arguments',{}),event)
                else:error(key,-32601,'Method not found.')
            except json.JSONDecodeError:error(key,-32700,'Invalid JSON.')
            except Exception as exc:error(key,-32602,str(exc))
    finally:
        with pending_lock:
            for event in pending.values():event.set()
        pool.shutdown(wait=True)

if __name__=='__main__':main()
