"""Manual start only. Preflight port binding precedes collectors."""
import argparse
import socket
import sys

import uvicorn

from wici.app import create_app
from wici.config import Config


def main():
    parser = argparse.ArgumentParser(description='WICI — sytuacja i ostrzeżenia; lokalny pilot')
    parser.add_argument('--demo',action='store_true',help='Odizolowany scenariusz offline')
    args = parser.parse_args()
    sock = None
    try:
        config = Config.load()
        sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        sock.bind(('127.0.0.1',config.port))
        sock.listen(128)
        print(f'http://127.0.0.1:{config.port} — zatrzymanie: Ctrl+C',flush=True)
        server = uvicorn.Server(uvicorn.Config(create_app(args.demo,config=config),host='127.0.0.1',port=config.port,workers=1,log_level='warning'))
        server.run(sockets=[sock])
        return 0 if server.started else 1
    except KeyboardInterrupt:
        return 0
    except (OSError,RuntimeError,ValueError) as exc:
        print(f'Nie można uruchomić aplikacji: {exc}',file=sys.stderr)
        return 1
    finally:
        if sock:
            sock.close()

if __name__=='__main__':
    raise SystemExit(main())
