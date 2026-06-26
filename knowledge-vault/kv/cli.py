from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kv import __version__
from kv.counsel import counsel_from_file
from kv.ingest import collect_inbox, inbox_status
from kv.painpoints import print_painpoints
from kv.prompt_pack import pack_counsel, pack_excel, pack_message, pack_propose
from kv.import_refs import count_references
from kv.obsidian_sync import sync_status, sync_to_obsidian
from kv.refine import refine_all
from kv.search import rebuild_index, search
from kv.watch import run_pipeline, watch_inbox


def _configure_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _maybe_sync(force: bool = False) -> None:
    from kv.config import load_config

    if not load_config().get("obsidian_sync_auto", True):
        return
    result = sync_to_obsidian(force=force)
    if result["dest"]:
        print(f"Obsidian 동기화: {result['synced']}개 복사, {result['skipped']}개 건너뜀")
        print(f"  → {result['dest']}")
    elif result["errors"]:
        print(f"Obsidian: {result['errors'][0]}")


def cmd_collect(args: argparse.Namespace) -> None:
    files = collect_inbox(force=args.force)
    print(f"수집 완료: {len(files)}개 MD 생성 -> vault/raw/")
    for f in files:
        print(f"  - {f.name}")


def cmd_refine(args: argparse.Namespace) -> None:
    files = refine_all(force=args.force)
    print(f"정제 완료: {len(files)}개 -> vault/refined/")
    for f in files:
        print(f"  - {f.name}")
    n = rebuild_index()
    print(f"검색 인덱스 갱신: {n}개 문서")
    _maybe_sync(force=args.force)


def cmd_sync(args: argparse.Namespace) -> None:
    result = sync_to_obsidian(force=args.force)
    if not result["dest"]:
        print("Obsidian vault 경로가 없습니다.")
        print("config.yaml 에 obsidian_vault 를 설정하세요.")
        print('  예: obsidian_vault: "C:/Users/jessy/Documents/Obsidian/내금고"')
        for e in result["errors"]:
            print(f"  - {e}")
        return
    print(f"Obsidian 동기화 완료: {result['synced']}개 복사, {result['skipped']}개 건너뜀")
    print(f"  경로: {result['dest']}")
    for e in result["errors"]:
        print(f"  오류: {e}")


def cmd_search(args: argparse.Namespace) -> None:
    hits = search(
        args.query,
        tag=args.tag,
        source_type=args.type,
        limit=args.limit,
    )
    if not hits:
        print("검색 결과 없음.")
        return
    for i, h in enumerate(hits, 1):
        tags = " ".join(f"#{t}" for t in h.tags if t)
        print(f"\n[{i}] {h.title}")
        print(f"    파일: {h.path}")
        if tags:
            print(f"    태그: {tags}")
        if h.keywords:
            print(f"    키워드: {', '.join(h.keywords[:8])}")
        if h.snippet:
            print(f"    ...{h.snippet}...")


def cmd_status(_: argparse.Namespace) -> None:
    st = inbox_status()
    print("=== Knowledge Vault 상태 ===")
    print("\n[inbox - 여기에 파일을 넣으세요]")
    for k, v in st["inbox"].items():
        print(f"  {k}/  ->  {v}개 파일")
    print(f"\n[vault/raw]     ->  {st['vault_raw']}개 MD")
    from kv.config import VAULT_REFINED
    refined = sum(1 for _ in VAULT_REFINED.glob("*.md"))
    print(f"[vault/refined] ->  {refined}개 MD")

    refs = count_references()
    if refs:
        print("\n[참조 문서 - E:\\project\\work05 볼트]")
        for k, v in refs.items():
            print(f"  {k}/  ->  {v}개")
        print(f"  합계: {sum(refs.values())}개 (검색 인덱스에 포함)")

    cfg = __import__("kv.config", fromlist=["load_config"]).load_config()
    w = cfg.get("whisper") or {}
    print(f"\n[Whisper] engine={w.get('engine', 'faster-whisper')}, model={w.get('model', 'base')}")

    print("\n[Obsidian]")
    vault_path = cfg.get("obsidian_vault", "")
    if vault_path:
        print(f"  vault: {vault_path}")
        routes = cfg.get("obsidian_routes", {})
        if routes:
            print(f"  라우팅: audio->{routes.get('audio')}, notes->{routes.get('notes', 'KnowledgeVault')}")
    obs = sync_status()
    if obs.get("last_sync"):
        print(f"  마지막 동기화: {obs.get('last_sync')}")
        print(f"  동기화된 수집 MD: {obs['synced_files']}개")
    else:
        print("  동기화 이력 없음 - python -m kv all 실행")


def cmd_pipeline(args: argparse.Namespace) -> None:
    r = run_pipeline(force=args.force)
    print(f"수집: {r['collected']}개 | 정제: {r['refined']}개 | 인덱스: {r['indexed']}개")
    sync = r["sync"]
    if sync.get("dest"):
        print(f"Obsidian 동기화: {sync['synced']}개 -> {sync['dest']}")
    elif sync.get("errors"):
        print(f"Obsidian: {sync['errors'][0]}")


def cmd_pain(_: argparse.Namespace) -> None:
    print_painpoints()


def cmd_ask(args: argparse.Namespace) -> None:
    from kv.ask import ask_pack

    out, hits, answer = ask_pack(args.question, top_k=args.top)
    print(f"검색된 자료 {len(hits)}건:")
    for i, h in enumerate(hits, 1):
        print(f"  [{i}] {h.title}")
    if answer:
        print("\n🤖 자동 답변 (로컬 LLM):\n")
        print(answer)
        print(f"\n저장: {out}")
    else:
        print(f"\n질의응답 프롬프트 팩: {out}")
        print("-> AI작업큐에서 열고 Claude에 붙여넣기 (로컬 LLM 켜면 자동 답변)")


def cmd_llm(args: argparse.Namespace) -> None:
    from kv.llm import (
        _base_url,
        _model,
        _provider,
        generate,
        has_key,
        llm_available,
        llm_enabled,
    )

    print(f"LLM: enabled={llm_enabled()}  provider={_provider()}  model={_model() or '(미설정)'}")
    print(f"  base_url={_base_url() or '(미설정)'}  키설정됨={has_key()}")
    if not llm_enabled():
        print("→ config.yaml 의 llm.enabled 를 true 로 바꾸세요.")
        return
    if not llm_available():
        print("→ 연결 불가. base_url/키/서버 상태(key.txt)를 확인하세요.")
        return
    print("→ 설정 OK")
    if args.prompt:
        print("\n응답:\n")
        print(generate(args.prompt) or "(응답 없음 — 엔드포인트/모델 확인)")


def cmd_profiles(_: argparse.Namespace) -> None:
    from kv.config import available_profiles, load_config, load_profile

    active = load_config().get("profile") or "(기본 insurance)"
    prof = load_profile()
    print(f"=== 활성 프로파일: {active} ===")
    print(f"  이름: {prof.get('name')}  /  카테고리: {prof.get('category')}")
    print("\n[용어]")
    for k, v in prof.get("labels", {}).items():
        print(f"  {k:10} -> {v}")
    print("\n[폴더]")
    for k, v in prof.get("folders", {}).items():
        print(f"  {k:10} -> {v}")
    avail = available_profiles()
    if avail:
        print(f"\n[사용 가능 프로파일] {', '.join(avail)}")
        print("  전환: config.yaml 의  profile:  값을 바꾸세요.")
        print("  새 산업: profiles/<이름>.yaml 추가.")


def cmd_counsel(args: argparse.Namespace) -> None:
    if args.audio:
        path = counsel_from_file(Path(args.audio), args.customer, args.channel)
    elif args.text:
        path = counsel_from_file(Path(args.text), args.customer, args.channel)
    else:
        print("--audio 또는 --text 필요")
        return
    text = path.read_text(encoding="utf-8")
    pack = pack_counsel(text, args.customer)
    from kv.search import rebuild_index
    rebuild_index()
    print(f"상담기록: {path}")
    print(f"Claude 프롬프트 팩: {pack}")
    print("-> Obsidian에서 AI작업큐 파일 열고 Claude에 붙여넣기")


def cmd_pack(args: argparse.Namespace) -> None:
    if args.mode == "propose":
        p = pack_propose(args.target)
    elif args.mode == "message":
        p = pack_message(args.target)
    elif args.mode == "excel":
        p = pack_excel(Path(args.target))
    elif args.mode == "counsel":
        text = Path(args.target).read_text(encoding="utf-8")
        p = pack_counsel(text, args.customer or "")
    else:
        print(f"알 수 없는 pack 모드: {args.mode}")
        return
    print(f"Claude 프롬프트 팩 생성: {p}")
    print("-> Obsidian AI작업큐 폴더에서 열고 Claude에 붙여넣기")


def cmd_watch(_: argparse.Namespace) -> None:
    watch_inbox()


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(
        prog="kv",
        description="다양한 자료 수집 -> 태그 MD -> 정제 -> Obsidian 동기화 -> 검색",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="inbox 파일을 MD로 수집")
    p_collect.add_argument("--force", action="store_true")
    p_collect.set_defaults(func=cmd_collect)

    p_refine = sub.add_parser("refine", help="raw MD 정제 + 인덱스 + Obsidian 동기화")
    p_refine.add_argument("--force", action="store_true")
    p_refine.set_defaults(func=cmd_refine)

    p_sync = sub.add_parser("sync", help="vault/refined -> Obsidian vault 복사")
    p_sync.add_argument("--force", action="store_true", help="변경 없어도 전체 재동기화")
    p_sync.set_defaults(func=cmd_sync)

    p_search = sub.add_parser("search", help="정제된 데이터 검색")
    p_search.add_argument("query", help="검색어")
    p_search.add_argument("--tag", help="태그 필터")
    p_search.add_argument("--type", dest="type", help="소스 유형")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", help="현재 상태")
    p_status.set_defaults(func=cmd_status)

    p_all = sub.add_parser("all", help="collect + refine + sync 한번에")
    p_all.add_argument("--force", action="store_true")
    p_all.set_defaults(func=cmd_pipeline)

    p_watch = sub.add_parser("watch", help="inbox 감시 자동화")
    p_watch.set_defaults(func=cmd_watch)

    p_pain = sub.add_parser("pain", help="index.html pain point -> 해결 명령")
    p_pain.set_defaults(func=cmd_pain)

    p_profiles = sub.add_parser("profiles", help="산업 프로파일 목록/현재 설정 보기")
    p_profiles.set_defaults(func=cmd_profiles)

    p_ask = sub.add_parser("ask", help="내 자료 기반 질의응답 (로컬 LLM 자동/Claude 붙여넣기)")
    p_ask.add_argument("question", help="질문")
    p_ask.add_argument("--top", type=int, default=5, help="참고할 자료 수")
    p_ask.set_defaults(func=cmd_ask)

    p_llm = sub.add_parser("llm", help="로컬 LLM(Ollama) 연결 확인/테스트")
    p_llm.add_argument("prompt", nargs="?", default="", help="테스트 프롬프트(선택)")
    p_llm.set_defaults(func=cmd_llm)

    p_counsel = sub.add_parser("counsel", help="녹취/전사 -> 상담기록 + 프롬프트팩")
    p_counsel.add_argument("--customer", "-c", required=True, help="고객명 (고객DB 파일명)")
    p_counsel.add_argument("--audio", help="녹음 파일 경로")
    p_counsel.add_argument("--text", help="전사 텍스트 파일 경로")
    p_counsel.add_argument("--channel", default="대면", choices=["대면", "전화", "화상"])
    p_counsel.set_defaults(func=cmd_counsel)

    p_pack = sub.add_parser("pack", help="Claude 프롬프트 팩 생성")
    p_pack.add_argument("mode", choices=["propose", "message", "excel", "counsel"])
    p_pack.add_argument("target", help="고객명 또는 파일 경로")
    p_pack.add_argument("--customer", "-c", default="", help="counsel 모드용 고객명")
    p_pack.set_defaults(func=cmd_pack)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
