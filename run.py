"""개발/운영 공용 실행 스크립트.

    python run.py                 # 127.0.0.1:8000
    python run.py --host 0.0.0.0 --port 8080
    python run.py --demo          # 데모 데이터 생성 후 기동
"""
from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> int:
    p = argparse.ArgumentParser(description="PC 자산관리 시스템 v1")
    p.add_argument("--host", default="127.0.0.1", help="바인딩 주소 (사내 공개 시 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="개발용 자동 재시작")
    p.add_argument("--demo", action="store_true", help="샘플 데이터를 생성한 뒤 기동")
    p.add_argument("--reset-demo", action="store_true", help="DB를 비우고 샘플 데이터를 다시 만든다")
    args = p.parse_args()

    if args.demo or args.reset_demo:
        from tools import make_demo
        make_demo.run(reset=args.reset_demo)

    if _port_in_use(args.host, args.port):
        print()
        print(f"  [오류] 포트 {args.port} 번을 이미 다른 프로그램이 쓰고 있습니다.")
        print()
        print("  다음 중 하나로 해결하세요.")
        print("    1. 이미 켜져 있는 자산관리 시스템 창에서 Ctrl+C 로 종료한 뒤 다시 실행")
        print(f"    2. 다른 포트로 실행:  python run.py --port {args.port + 1}")
        print(f"    3. 사용 중인 프로그램 확인:  netstat -ano | findstr :{args.port}")
        print(flush=True)
        return 1

    from app.main import bootstrap
    bootstrap()

    _banner(args.host, args.port)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload,
                log_level="info")
    return 0


def _port_in_use(host: str, port: int) -> bool:
    """기동 전에 포트를 확인해, 알아보기 어려운 소켓 오류 대신 안내를 보여준다."""
    import socket
    bind_host = "" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((bind_host, port))
            return False
        except OSError:
            return True


def _banner(host: str, port: int) -> None:
    """시작 안내. 배치 파일 대신 여기서 출력한다.

    Windows 콘솔에서 파이썬은 유니코드로 직접 출력하므로 코드페이지(chcp)와 무관하게
    한글이 깨지지 않는다. 배치 파일에 한글을 넣으면 인코딩 문제가 생기므로 넣지 않는다.
    """
    local = f"http://127.0.0.1:{port}"
    print()
    print("  PC 자산관리 시스템 v1 을 시작합니다.")
    print()
    print(f"    이 PC에서 접속    {local}")
    if host == "0.0.0.0":
        for addr in _lan_addresses():
            print(f"    사내망에서 접속   http://{addr}:{port}")
    print()
    print("  종료하려면 이 창에서 Ctrl+C 를 누르세요.")
    print(flush=True)


def _lan_addresses() -> list[str]:
    """사내망에서 접속할 주소를 안내하기 위해 이 PC의 IPv4 주소를 찾는다."""
    import socket
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


if __name__ == "__main__":
    sys.exit(main())
