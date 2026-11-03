#!/usr/bin/env python3
# Public repository maintenance utility. Never publish runtime secrets or private backups.
"""Conservative Git sync for one known repository, after a one-time baseline merge.

No stage-all, no auto commit of arbitrary local changes, no hard reset, no forced push.
Auto-merges *disjoint changed paths only*, then tests before publishing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

EXPECTED_REPO = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"cuihanzhe955-commits/SmartMoneyAITrader(?:\.git)?/?$", re.I
)
DEFAULT_PROJECT = Path(__file__).resolve().parents[2]
NO_BACKUP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "runtime", ".next", "coverage", ".idea"}
MAX_ZIP_ITEM = 120 * 1024 * 1024
SENSITIVE_PATTERN = re.compile(r"(^|/)(?:\.env(?!\.example$)|runtime|backup(?:s)?|secrets?|credentials?|\.ssh|\.aws)(?:/|$)|\.(?:pem|key|p12|pfx|db|sqlite|sqlite3)$|(?:^|/)(?:prompt[^/]*|codex[^/]*)\.(?:txt|md)$", re.I)
SECRET_CONTENT = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{18,}|\bgh[opusr]_[A-Za-z0-9]{25,}|\bsk-proj-[A-Za-z0-9_-]{20,}")
CORE_LAUNCHER = {"start.bat", "start.cmd", "install.bat", "stop.bat", "launch.py", "terminal_host.py", "scripts/launcher.py", "scripts/build_source_package.py", "tests/test_launcher.py", "tests/test_package.py"}

class Blocked(Exception):
    pass


def go(argv=None):
    ap = argparse.ArgumentParser(description="Smart Money AI Trader 中文安全双向同步")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT))
    ap.add_argument("--mode", choices=["sync", "audit"], default="sync")
    args = ap.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    backup_root = project.parent / "SmartMoneyAITrader_SYNC_BACKUPS"
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    dest = backup_root / stamp
    dest.mkdir(parents=True, exist_ok=False)
    report = dest / "同步报告.txt"
    observations = ["Smart Money AI Trader · 中文安全同步报告", f"开始时间：{dt.datetime.now().astimezone().isoformat()}", f"主工程：{project}", f"运行模式：{'一键安全同步' if args.mode=='sync' else '仅检查'}", f"本轮备份目录：{dest}"]
    any_changes_to_git = False
    
    def note(value):
        s = str(value)
        observations.append(s)
        print(s, flush=True)
        report.write_text("\n".join(observations) + "\n", encoding="utf-8")

    def run(*cmd, check=True, timeout=600, env=None):
        proc = subprocess.run(cmd, cwd=project, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, env=env)
        if check and proc.returncode:
            raise Blocked(f"命令执行失败（退出码 {proc.returncode}）：{' '.join(map(str,cmd))}\n错误详情：{proc.stderr[-1400:]}\n标准输出：{proc.stdout[-1400:]}")
        return proc

    def git(*cmd, check=True):
        return run("git", *cmd, check=check)

    def check_publish(changed):
        for path in sorted(changed):
            q = path.replace("\\", "/")
            if SENSITIVE_PATTERN.search(q) or "计划书" in q or "私有" in q or "_备份" in q:
                raise Blocked(f"待上传提交含疑似私密文件，已阻止：{q}")
            if q.endswith((".md", ".txt", ".rst")) and (q == "README.md" or q == "使用说明.md" or q.startswith("docs/")):
                p = project / q
                if p.is_file():
                    data = p.read_text(encoding="utf-8", errors="replace")
                    if re.search(r"codex", data, flags=re.I):
                        raise Blocked(f"公开文档含不应公开的内部开发工具名称，已阻止：{q}")
                    if SECRET_CONTENT.search(data):
                        raise Blocked(f"公开文档疑似包含密钥，已阻止：{q}")
            if q.endswith((".py", ".js", ".ts", ".tsx", ".json", ".env", ".yml", ".yaml")):
                p = project / q
                if p.is_file() and p.stat().st_size < 3_000_000 and SECRET_CONTENT.search(p.read_text(encoding="utf-8", errors="replace")):
                    raise Blocked(f"待上传文件疑似包含硬编码凭证，已阻止：{q}")

    def diff_names(a,b):
        raw = git("diff", "--name-only", "-z", a,b).stdout
        return set(x for x in raw.split("\0") if x)

    def offline_checks(changed):
        note("[步骤 5/6] 正在运行离线测试（不会执行真实交易订单）……")
        safe_env = os.environ.copy()
        # Do not expose ordinary known account/API credentials to a test process.
        for k in list(safe_env):
            if re.search(r"(?:OPENAI|OKX|GATE|BINANCE|TELEGRAM|FEISHU|SENSENOVA).*(?:API|KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE)", k, re.I):
                safe_env.pop(k, None)
        safe_env["SMART_MONEY_EXECUTION"] = "paper"
        if not (project / "tests" / "run_offline.py").is_file():
            raise Blocked("找不到 tests/run_offline.py，无法完成离线验收；禁止自动推送。")
        p = run(sys.executable, "-B", "tests/run_offline.py", timeout=240, check=False, env=safe_env)
        note(f"  离线回归测试：退出码={p.returncode}；摘要：{p.stdout[-550:].strip()}")
        if p.returncode:
            raise Blocked(f"离线回归测试未通过：{p.stderr[-1200:]} {p.stdout[-1200:]}")
        if importlib.util.find_spec("pytest") is not None:
            tests = [x for x in ("tests/test_launcher.py","tests/test_package.py") if (project/x).exists()]
            if tests:
                p = run(sys.executable, "-m", "pytest", "-q", *tests, timeout=240, check=False, env=safe_env)
                note(f"  启动器与打包测试：退出码={p.returncode}；摘要：{p.stdout[-550:].strip()}")
                if p.returncode:
                    raise Blocked(f"启动器/打包测试未通过：{p.stderr[-1200:]} {p.stdout[-1200:]}")
        elif changed.intersection(CORE_LAUNCHER):
            raise Blocked("启动器/打包相关文件发生变动，但尚未安装 pytest；请先配置测试依赖。")
        if any(p.startswith("frontend/") for p in changed):
            npm = shutil.which("npm")
            if not npm or not (project / "frontend" / "node_modules").exists():
                raise Blocked("前端发生变动，但 npm 或 frontend/node_modules 不存在；请安装依赖后再检查。")
            p=run(npm, "--prefix", "frontend", "run", "typecheck", timeout=240, check=False, env=safe_env)
            note(f"  前端 TypeScript 类型检查：退出码={p.returncode}；摘要：{p.stdout[-550:].strip()}")
            if p.returncode:
                raise Blocked(f"前端类型检查未通过：{p.stderr[-1200:]} {p.stdout[-1200:]}")
        if git("diff", "--check", check=False).returncode or git("diff", "--cached", "--check", check=False).returncode:
            raise Blocked("Git 差异空白/补丁检查失败，请先修复。")

    try:
        note("==================================================")
        note("SMART MONEY · 中文双端安全同步工具")
        note(f"本次选择：{'一键安全同步' if args.mode=='sync' else '只检查不修改'}")
        note("安全策略：先备份；有冲突、未提交文件或测试失败就停止，绝不强推。")
        note("==================================================")
        if not project.is_dir():
            raise Blocked("找不到主工程目录。请修改 .cmd 文件的 SMARTMONEY_PROJECT 路径；工具不会自动初始化新仓库。")
        if not shutil.which("git"):
            raise Blocked("找不到 Git。请先安装 Git for Windows 并确认它位于 PATH。")
        root = Path(git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
        if root != project:
            raise Blocked(f"选择的目录不是 Git 仓库根目录。实际仓库根目录：{root}")
        origin = git("remote", "get-url", "origin").stdout.strip()
        if not EXPECTED_REPO.fullmatch(origin):
            raise Blocked(f"origin 不是预期的 SmartMoneyAITrader 官方仓库，已阻止操作。当前 origin：{origin}")
        branch = git("symbolic-ref", "--short", "HEAD").stdout.strip()
        if branch != "main":
            raise Blocked(f"当前位于分支 {branch!r}，不是 main；请先人工确认分支及同步方案。")
        git_dir = Path(git("rev-parse", "--absolute-git-dir").stdout.strip())
        for item in ("MERGE_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
            if (git_dir/item).exists():
                raise Blocked(f"发现尚未结束的 Git 操作：{item}。请处理后再运行。")
        original_head = git("rev-parse", "HEAD").stdout.strip()
        note(f"[步骤 1/6] 已核对仓库身份与分支。\n远端 origin：{origin}\n当前分支：{branch}\n原本地提交：{original_head}")
        # Local-only source snapshot; no runtime or external upload. No deletion/overwrite.
        try:
            bundle = dest / "git_history.bundle"
            git("bundle", "create", str(bundle), "--all")
            if not bundle.is_file() or bundle.stat().st_size == 0:
                raise Blocked("无法创建可验证的 Git 历史备份。")
            note(f"[步骤 2/6] Git 提交历史已备份：{bundle.name}（{bundle.stat().st_size} 字节）")
            snapshot = dest / "source_snapshot.zip"
            count, skipped = 0, []
            with zipfile.ZipFile(snapshot, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as z:
                for folder, dirs, files in os.walk(project):
                    dirs[:] = [d for d in dirs if d not in NO_BACKUP_DIRS and not Path(folder,d).is_symlink()]
                    for fn in files:
                        path = Path(folder,fn)
                        rel = path.relative_to(project)
                        if path.is_symlink() or path.stat().st_size > MAX_ZIP_ITEM:
                            skipped.append(str(rel))
                            continue
                        z.write(path, rel.as_posix())
                        count += 1
            if snapshot.stat().st_size == 0:
                raise Blocked("源码快照 ZIP 创建失败。")
            note(f"源码快照已备份：{snapshot.name}（{snapshot.stat().st_size} 字节，共 {count} 个文件）")
            note("源码快照排除目录（仅对该 ZIP 生效）：" + ", ".join(sorted(NO_BACKUP_DIRS)))
            if skipped:
                note("未写入源码 ZIP 的项目（符号链接或超大文件）：" + ", ".join(skipped[:25]))
        except Exception as e:
            raise Blocked(f"备份失败，为防止丢失数据，停止同步：{e}")
        status = git("status", "--porcelain=v1", "--untracked-files=all").stdout
        (dest/"初始Git状态.txt").write_text(status,encoding="utf-8")
        if status.strip():
            note("检测到未提交的本地改动。已完成备份，不会自动覆盖工作区。")
            raise Blocked("请先审阅本地修改、排除密钥与私有数据，再提交适合公开的文件。工作区干净后重新运行。")
        note("[步骤 3/6] 工作区干净，正在从 GitHub 获取最新提交信息（git fetch）……")
        git("fetch", "origin", "main")
        remote_head = git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        note(f"远端 main 最新提交：{remote_head}")
        base = git("merge-base", "HEAD", "origin/main", check=False)
        if base.returncode:
            raise Blocked("本地与远端 Git 提交历史没有共同祖先。首次双端整合必须人工审阅，不能自动选择一方。")
        common=base.stdout.strip()
        changes = git("rev-list", "--left-right", "--count", "HEAD...origin/main").stdout.strip().split()
        if len(changes)!=2:
            raise Blocked("无法确认本地和远端各自领先多少提交。")
        ahead,behind=map(int,changes)
        note(f"[步骤 4/6] 双端提交对比：本地领先 {ahead} 个提交；远端领先 {behind} 个提交；共同祖先：{common}")
        local_paths=diff_names(common,"HEAD")
        remote_paths=diff_names(common,"origin/main")
        # Deletions / renames need explicit review even if no text conflict.
        # This prevents automated fast-forward from silently removing useful features.
        local_deletions = git("diff", "--diff-filter=DR", "--name-only", common, "HEAD").stdout.strip()
        remote_deletions = git("diff", "--diff-filter=DR", "--name-only", common, "origin/main").stdout.strip()
        if local_deletions or remote_deletions:
            (dest/"删除或重命名待审查.txt").write_text(
                "本地删除/重命名：\n" + local_deletions + "\n远端删除/重命名：\n" + remote_deletions + "\n",
                encoding="utf-8"
            )
            raise Blocked("发现删除或重命名操作。为防止误删已有功能，请先审阅差异，停止自动同步。")
        (dest/"本地变更路径.txt").write_text("\n".join(sorted(local_paths))+"\n",encoding="utf-8")
        (dest/"远端变更路径.txt").write_text("\n".join(sorted(remote_paths))+"\n",encoding="utf-8")
        (dest/"远端完整文件树.txt").write_text(git("ls-tree", "-r", "--name-only", "origin/main").stdout,encoding="utf-8")
        (dest/"本地完整文件树.txt").write_text(git("ls-tree", "-r", "--name-only", "HEAD").stdout,encoding="utf-8")
        overlap=local_paths & remote_paths
        note(f"文件差异：本地改动 {len(local_paths)} 个路径，远端改动 {len(remote_paths)} 个路径，双方同路径改动 {len(overlap)} 个。")
        if overlap:
            (dest/"冲突文件待审查.txt").write_text("\n".join(sorted(overlap))+"\n",encoding="utf-8")
            raise Blocked("本地和远端修改了同名路径，必须逐文件三方审阅。冲突路径示例：" + ", ".join(sorted(overlap)[:12]))
        if args.mode=="audit":
            note("[完成] 仅检查模式：未执行合并、提交、快进更新或推送。请查看中文同步报告。")
            return 0
        if ahead==0 and behind==0:
            note("[完成] 本地与 GitHub 已经一致，无须推送。")
            return 0
        if ahead==0 and behind>0:
            note("远端有新提交、本地无新提交。正在执行安全快进更新（不覆盖本地提交）……")
            git("merge", "--ff-only", "origin/main")
            any_changes_to_git=True
            offline_checks(remote_paths)
            note("[成功] 已把远端新提交安全更新到本地，离线测试通过，不需要推送。")
            return 0
        if ahead>0 and behind==0:
            note("本地有新提交、远端无新提交。开始检查敏感信息并执行测试……")
            check_publish(local_paths)
            offline_checks(local_paths)
            if git("status", "--porcelain=v1", "--untracked-files=all").stdout.strip():
                raise Blocked("测试改变了工作区内容。请审阅这些修改后再推送。")
            git("push", "origin", "main:main")
            note("[步骤 6/6] 正常推送已完成，正在重新获取 GitHub 提交以核实结果……")
            git("fetch", "origin", "main")
            if git("rev-parse", "HEAD").stdout.strip() != git("rev-parse", "origin/main").stdout.strip():
                raise Blocked("推送后核对失败：远端提交与本地提交不一致，请调查。")
            note("[成功] 同步完成！本地与 GitHub 最新提交一致，离线测试通过。")
            return 0
        if ahead>0 and behind>0:
            note("本地和远端都有新提交，但修改路径没有重叠；开始进行可审查的自动合并……")
            git("merge", "--no-commit", "--no-ff", "origin/main")
            any_changes_to_git=True
            try:
                check_publish(local_paths)
                offline_checks(local_paths|remote_paths)
                unstaged=git("diff", "--name-only").stdout.strip()
                new_untracked=git("ls-files", "--others", "--exclude-standard").stdout.strip()
                if unstaged or new_untracked:
                    raise Blocked("合并或测试留下未暂存、未跟踪文件。请先审阅，不允许自动推送。")
                git("commit", "--no-edit")
            except Exception as e:
                # Initial worktree was clean; abort only this pending merge, never hard reset.
                abort = git("merge", "--abort", check=False)
                note("本轮未提交的合并已经通过 git merge --abort 撤回" if abort.returncode==0 else "合并无法自动撤回，可能仍处于进行中状态；请人工检查，禁止推送")
                raise Blocked(str(e))
            git("push", "origin", "main:main")
            git("fetch", "origin", "main")
            if git("rev-parse", "HEAD").stdout.strip()!=git("rev-parse", "origin/main").stdout.strip():
                raise Blocked("推送后核实远端结果失败。")
            note("[成功] 两端无重叠的改动已经合并、通过离线测试并正常推送到 GitHub。")
            return 0
        raise Blocked("出现无法识别的分支状态；已停止同步。")
    except Blocked as e:
        note("[安全停止] 原因：" + str(e))
        if any_changes_to_git:
            note("注意：本轮曾更新本地 Git 状态或进行合并，尚未确认最终同步；请参考初始备份和 git status，不要手动强制覆盖。")
        note("没有执行强推、硬重置或破坏性清理。如果有未完成的合并，请检查 Git 状态后处理。")
        return 2
    except Exception as e:
        note("[异常停止] 程序出现未预料的错误：" + repr(e))
        return 3
    finally:
        report.write_text("\n".join(observations)+"\n",encoding="utf-8")
        print(f"\n本轮中文报告位置：{report}", flush=True)

if __name__ == "__main__":
    sys.exit(go())