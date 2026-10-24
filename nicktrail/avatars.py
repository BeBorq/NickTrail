"""Small raster avatar proxy: no browser requests to arbitrary remote URLs."""
import json
from .network import Client,Limit
import http.client
from .identity import normalize

def fetch(store,id):
    data=json.loads(store.node(id)['data']);url=data.get('avatar_url')
    if not isinstance(url,str):return None
    try:result=Client(queries=2,seconds=10,delay=0,image_resources=True).get(normalize(url))
    except (ValueError,OSError,Limit,http.client.HTTPException):return None
    if result['state']!='found' or not isinstance(result.get('bytes'),bytes):return None
    body=result['bytes'];mime=result['content_type']
    valid=(mime=='image/png' and body.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and body.startswith(b'\xff\xd8\xff')) or (mime=='image/webp' and body.startswith(b'RIFF') and body[8:12]==b'WEBP')
    return (body,mime) if valid and len(body)<=262144 else None
