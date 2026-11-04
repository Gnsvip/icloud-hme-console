"""Synthetic benchmark, never reads real account or mail data."""
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mail_cache
import inventory_manager


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(baseline):
    old_cache = load('baseline_cache', baseline / 'mail_cache.py')
    old_inventory = load('baseline_inventory', baseline / 'inventory_manager.py')
    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        payload = {str(i): {'id': str(i), 'body': 'Synthetic mail content. ' * 130} for i in range(6500)}
        incoming = {str(i): {'id': str(i), 'body': 'new synthetic body'} for i in range(6500,6530)}
        for name, module in [('before',old_cache),('after',mail_cache)]:
            module.CACHE_FILE=tmp / (name+'.json')
            cache=module.MailCache()
            cache._data={'one': {'inbox_emails':[], 'alias_emails':{}, 'message_bodies':payload.copy()}}
            cache._save()
            size=module.CACHE_FILE.stat().st_size
            with patch.object(cache,'_save',wraps=cache._save) as save:
                start=time.perf_counter()
                if name=='before':
                    for key,value in incoming.items():cache.set_message('one',key,value)
                else:cache.set_messages('one',incoming)
                result[name]={'initial_cache_bytes':size,'body_writes':save.call_count,'body_batch_ms':round((time.perf_counter()-start)*1000,2)}
            rows=[{'email':f'box{i:04}@icloud.com','account_id':'one','label':'synthetic'} for i in range(1593)]
            inventory=module_inv=(old_inventory if name=='before' else inventory_manager).InventoryManager(tmp/(name+'-inventory.json'))
            inventory.sync_aliases(rows)
            with patch.object(inventory,'save',wraps=inventory.save) as save:
                start=time.perf_counter()
                for _ in range(5):inventory.sync_aliases(rows)
                result[name].update(inventory_noop_writes=save.call_count,inventory_five_sync_ms=round((time.perf_counter()-start)*1000,2))
            values=list(inventory.load()['items'].values())
            result[name]['inventory_payload_bytes']=len(json.dumps(values if name=='before' else values[:20],ensure_ascii=False).encode())
    print(json.dumps(result,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]))
