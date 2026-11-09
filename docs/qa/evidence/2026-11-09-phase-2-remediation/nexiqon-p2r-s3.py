import asyncio,socket,uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from nexiqon_core.blobs import MemoryBlobStore
from nexiqon_core.fetch import FetchPolicy,SafeFetcher
from nexiqon_ingestion.plugins.context import Context
from nexiqon_ingestion.plugins.connectors import S3Connector

async def main():
 good=[];bad=[]
 async def handle(reader,writer,hits):
  request=await reader.readuntil(b'\r\n\r\n')
  first=request.splitlines()[0].decode();hits.append(first)
  body=(b'<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>a.md</Key><Size>3</Size><ETag>e</ETag></Contents></ListBucketResult>' if 'list-type=2' in first else b'# A')
  writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
  await writer.drain();writer.close();await writer.wait_closed()
 safe=await asyncio.start_server(lambda r,w:handle(r,w,good),'127.0.0.2',0)
 port=safe.sockets[0].getsockname()[1]
 unsafe=await asyncio.start_server(lambda r,w:handle(r,w,bad),'127.0.0.1',port)
 original=socket.getaddrinfo
 def rebound(host,*args,**kwargs):
  name=host.decode() if isinstance(host,bytes) else host
  return original('127.0.0.1' if name=='s3.rebind.example' else host,*args,**kwargs)
 async def approve(host,port):return ['127.0.0.2']
 fetch=SafeFetcher(FetchPolicy(allowed_ports=[port],allowed_private_cidrs=['127.0.0.2/32']),resolver=approve)
 try:
  with TemporaryDirectory() as scratch,patch('socket.getaddrinfo',rebound):
   tenant=uuid.uuid4()
   ctx=Context(tenant_id=tenant,http=fetch,blobs=MemoryBlobStore(),scratch=Path(scratch),credentials={f'{tenant}/qa':{'access_key':'qa','secret_key':'qa'}},max_items=10,max_bytes=10000)
   config={'endpoint':f'http://s3.rebind.example:{port}','bucket':'docs','credentials_ref':'qa'}
   connector=S3Connector()
   items=[i async for i in connector.discover(ctx,config)]
   content=await connector.fetch(ctx,config,items[0],None)
   assert content.data==b'# A'
   assert len(good)==2 and not bad,(good,bad)
   print('PASS: listing and fetch reached only the approved 127.0.0.2 listener; rebound 127.0.0.1 received no requests')
 finally:
  await fetch.aclose();safe.close();unsafe.close();await safe.wait_closed();await unsafe.wait_closed()
asyncio.run(main())
