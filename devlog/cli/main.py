"""轻量命令行外壳：解析参数、调用 runner、打印结果。"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from devlog import __version__
from devlog.cli import runner
from devlog.core.git_source.scanner import GitSourceError
from devlog.core.llm.base import LLMError
from devlog.core.review.markdown import ReviewExportError
from devlog.core.storage.database import DevLogDB, DatabaseError
from devlog.server.app import create_app


def _date_argument(value: str) -> datetime:
    """把 --since/--until 解析成带时区的 datetime。"""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "日期格式无效，请使用 ISO 格式，例如 2026-09-01 或 2026-09-01T09:00:00"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构建 DevLog V1 的完整命令树。"""

    parser = argparse.ArgumentParser(
        prog="devlog",
        description="本地开发复盘工具：扫描 Git 历史并生成可确认的复盘草稿。",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="状态数据库路径（默认 ~/.devlog/devlog.db）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="命令")

    init_parser = sub.add_parser("init", help="注册一个 Git 仓库")
    init_parser.add_argument(
        "path", nargs="?", default=None, help="仓库路径（默认当前目录）"
    )

    scan_parser = sub.add_parser("scan", help="把 Git 历史扫描进缓存数据库")
    scan_parser.add_argument(
        "path", nargs="?", default=None, help="仓库路径（默认当前目录）"
    )
    scan_parser.add_argument(
        "--reset",
        action="store_true",
        help="清空该项目缓存后重新全量扫描（例如 rebase/force push 之后）",
    )

    review_parser = sub.add_parser(
        "review", help="复盘草稿：生成、查看、确认与导出"
    )
    review_sub = review_parser.add_subparsers(
        dest="review_command", required=True, metavar="子命令"
    )

    generate_parser = review_sub.add_parser(
        "generate", help="生成并保存一份结构化复盘草稿"
    )
    generate_parser.add_argument(
        "path", nargs="?", default=None, help="仓库路径（默认当前目录）"
    )
    generate_parser.add_argument("--since", type=_date_argument, help="起始时间（含）")
    generate_parser.add_argument("--until", type=_date_argument, help="结束时间（含）")
    generate_parser.add_argument(
        "--offline",
        action="store_true",
        help="不调用 AI，用 Git 事实生成规则摘要（适合演示/测试）",
    )

    list_parser = review_sub.add_parser(
        "list", help="列出项目的复盘草稿（不带 --draft）或查看某份草稿详情"
    )
    list_parser.add_argument(
        "path", nargs="?", default=None, help="仓库路径（默认列出全部项目）"
    )
    list_parser.add_argument(
        "--draft", type=int, default=None, help="查看指定草稿 ID 的逐条论断"
    )

    confirm_parser = review_sub.add_parser(
        "confirm", help="确认 AI 推断（仅 ai_pending → confirmed）"
    )
    confirm_parser.add_argument("draft_id", type=int, help="草稿 ID")
    confirm_parser.add_argument(
        "claim_ids", type=int, nargs="*", help="要确认的论断 ID"
    )
    confirm_parser.add_argument("--all", action="store_true", help="确认全部待确认项")
    confirm_parser.add_argument("--note", default=None, help="给论断补充备注")

    export_parser = review_sub.add_parser(
        "export", help="把草稿导出为 Markdown 文件"
    )
    export_parser.add_argument("draft_id", type=int, help="草稿 ID")
    export_parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认 <仓库>/docs/retrospectives/）",
    )

    serve_parser = sub.add_parser(
        "serve",
        help="启动本地 API 服务（配合 Web 前端或接口调试）",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址（默认 127.0.0.1，仅本机可访问）",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="监听端口（默认 8000）",
    )
    serve_parser.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="启动后自动在默认浏览器打开界面（一键启动脚本会用这个）",
    )

    return parser


def browser_url(host: str, port: int) -> str:
    """把监听地址翻译成浏览器能打开的地址。

    `0.0.0.0` 表示「监听所有网卡」，它本身不是一个可访问的地址，
    所以展示给浏览器时统一换成回环地址 127.0.0.1。
    """

    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}"


def schedule_browser_open(url: str, delay: float = 1.5) -> threading.Timer:
    """延迟一小段时间再打开浏览器，避免服务还没起来就打开一个空白页。"""

    timer = threading.Timer(delay, webbrowser.open, args=[url])
    timer.daemon = True
    timer.start()
    return timer


def _fmt_day(when: datetime) -> str:
    return when.date().isoformat()


def _print_summary_line(summary) -> None:
    print(
        f"#{summary.draft_id}  {summary.project_name} | "
        f"{_fmt_day(summary.range_start)} ~ {_fmt_day(summary.range_end)} | "
        f"论断 {summary.total_claims} 条"
        f"（AI 待确认 {summary.ai_pending_claims}，"
        f"已确认 {summary.confirmed_claims}）"
    )


def main(argv: list[str] | None = None) -> int:
    """供 `python -m devlog` 与测试使用的入口。"""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        db_path = Path(args.db).expanduser() if args.db else None

        if args.command == "serve":
            app = create_app(db_path=db_path)
            url = browser_url(args.host, args.port)
            web_dist = getattr(getattr(app, "state", None), "web_dist", None)
            if web_dist:
                print(f"DevLog 界面地址：{url}")
            else:
                print(
                    "未找到前端构建产物（devlog/web/dist），当前只提供 API。"
                    "先执行 start-devlog.bat 或 `pnpm build` 生成界面。"
                )
            if args.open_browser:
                schedule_browser_open(url)
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")
            return 0

        with DevLogDB(db_path) as db:
            if args.command == "init":
                result = runner.cmd_init(db, args.path)
                print(
                    f"已注册项目 #{result.project_id}：{result.project_name} "
                    f"（{result.project_path}）"
                )
            elif args.command == "scan":
                result = runner.cmd_scan(db, args.path, reset=args.reset)
                verb = "已重置并重新扫描" if result.reset else "扫描完成"
                print(
                    f"{verb}：共 {result.total_events} 条提交，"
                    f"本次新写入 {result.inserted_events} 条"
                )
            elif args.command == "review":
                if args.review_command == "generate":
                    result = runner.cmd_review_generate(
                        db,
                        args.path,
                        since=args.since,
                        until=args.until,
                        offline=args.offline,
                    )
                    mode = "（离线：规则摘要，未调用 AI）" if args.offline else ""
                    print(
                        f"已生成草稿 #{result.draft_id}：{result.project_name} "
                        f"{_fmt_day(result.range_start)} ~ "
                        f"{_fmt_day(result.range_end)}，"
                        f"论断 {result.claim_count} 条"
                        f"（AI 待确认 {result.ai_pending_count}），"
                        f"引导问题 {result.question_count} 个 {mode}"
                    )
                elif args.review_command == "list":
                    if args.draft is not None:
                        record = runner.cmd_review_show(db, args.draft)
                        print(
                            f"草稿 #{record.draft_id} · {record.project_name} · "
                            f"{_fmt_day(record.draft.range_start)} ~ "
                            f"{_fmt_day(record.draft.range_end)}"
                        )
                        for item in record.stored_claims:
                            label = {
                                "fact": "事实",
                                "ai_pending": "AI 待确认",
                                "confirmed": "已确认",
                                "edited": "已修改",
                            }.get(item.claim.status.value, item.claim.status.value)
                            print(
                                f"  [{item.id}] {label} · {item.claim.section} · "
                                f"{item.claim.text}"
                            )
                    else:
                        summaries = runner.cmd_review_list(db, args.path)
                        if not summaries:
                            print("没有复盘草稿。先执行 review generate 生成一份。")
                        else:
                            for summary in summaries:
                                _print_summary_line(summary)
                elif args.review_command == "confirm":
                    result = runner.cmd_review_confirm(
                        db,
                        args.draft_id,
                        claim_ids=args.claim_ids,
                        confirm_all=args.all,
                        note=args.note,
                    )
                    print(
                        f"已确认 {result.changed} 条；草稿 #{result.draft_id} "
                        f"还剩 {result.remaining_pending} 条 AI 待确认。"
                    )
                elif args.review_command == "export":
                    target = runner.cmd_review_export(
                        db, args.draft_id, output=args.output
                    )
                    print(f"已导出复盘文档：{target}")
        return 0
    except (
        runner.CLIUsageError,
        GitSourceError,
        DatabaseError,
        ReviewExportError,
        LLMError,
    ) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
