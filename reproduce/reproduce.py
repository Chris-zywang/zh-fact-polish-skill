#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键复现：确定性的部分。

运行方式（在本文件所在目录）：
    python reproduce.py

它会做三件事：
1. 跑 79 项单元测试；
2. 用 examples/Q30 的原稿、账本、终稿重跑 extract→verify→guard，核对输出；
3. 用 examples/Q16 做同样的事。

不需要联网，也不需要 API Key。它复现的是“检查”这一半：
同样的输入、同样的账本，会得到同样的修改单和守门结论。
文章生成（模型写作）那一半是随机的，不在本脚本范围内。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # 源码包根目录
SCRIPT_DIRS = [os.path.join(ROOT, "zh-fact-polish", "scripts"),
               os.path.join(ROOT, "skill", "zh-fact-polish", "scripts")]
SCRIPTS = next((d for d in SCRIPT_DIRS if os.path.isdir(d)), SCRIPT_DIRS[0])
EXAMPLES = os.path.join(HERE, "examples")
PY = sys.executable

CASES = {
    "Q30": {"claims": 8, "trusted": 6, "pending": 2, "guard_exit": 0},
    "Q16": {"claims": 10, "trusted": 8, "pending": 2, "guard_exit": 0},
}


def run(args, cwd):
    return subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def check_tests():
    if os.path.isdir(os.path.join(ROOT, "tests")):
        args = ["-m", "unittest", "discover", "-s", "tests"]
    elif os.path.isdir(os.path.join(ROOT, "skill", "tests")):
        args = ["-m", "unittest", "discover", "-s", "skill/tests"]
    else:
        print("[SKIP] 未找到 tests/ 目录，跳过单元测试")
        return True
    r = run(args, ROOT)
    text = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"Ran (\d+) tests", text)
    n = int(m.group(1)) if m else 0
    ok = ("OK" in text) and n == 79
    print("[%s] 单元测试：%d 项，%s" % ("PASS" if ok else "FAIL", n, "全部通过" if ok else "有失败"))
    return ok


def check_case(name, expect):
    src = os.path.join(EXAMPLES, name)
    tmp = tempfile.mkdtemp(prefix="repro_%s_" % name)
    try:
        shutil.copy(os.path.join(src, "draft.md"), tmp)
        material = os.path.join(src, "material.md")
        args = [os.path.join(SCRIPTS, "fp_extract.py"), "draft.md", "--workdir", "work"]
        if os.path.exists(material):
            shutil.copy(material, tmp)
            args += ["--material", "material.md"]
        r = run(args, tmp)
        ledger_path = os.path.join(tmp, "work", "ledger.json")
        if r.returncode != 0 or not os.path.exists(ledger_path):
            print("[FAIL] %s：抽取失败\n%s" % (name, (r.stdout or "") + (r.stderr or "")))
            return False
        got_claims = len(json.load(open(ledger_path, encoding="utf-8")).get("claims", []))

        # 用存档账本覆盖空账本，保证检查部分的输入完全一致
        ledger = json.load(open(os.path.join(src, "ledger.json"), encoding="utf-8"))
        if os.path.exists(material):
            ledger["material_path"] = os.path.join(tmp, "material.md")
        json.dump(ledger, open(ledger_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

        r = run([os.path.join(SCRIPTS, "fp_verify.py"), "--workdir", "work"], tmp)
        report = ""
        rp = os.path.join(tmp, "work", "report.md")
        if os.path.exists(rp):
            report = open(rp, encoding="utf-8").read()
        m = re.search(r"可信 (\d+) / 待验证 (\d+)", report)
        trusted, pending = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)

        shutil.copy(os.path.join(src, "output.md"), tmp)
        r = run([os.path.join(SCRIPTS, "fp_guard.py"), "output.md", "--workdir", "work"], tmp)
        guard_exit = r.returncode
        gtext = (r.stdout or "") + (r.stderr or "")
        m2 = re.search(r"待验证 (\d+) 条", gtext)
        guard_pending = int(m2.group(1)) if m2 else -1

        ok = (got_claims == expect["claims"]
              and trusted == expect["trusted"] and pending == expect["pending"]
              and guard_exit == expect["guard_exit"] and guard_pending == 0)
        print("[%s] %s：抽取 %d 条（预期 %d）；修改单 可信 %d / 待验证 %d（预期 %d/%d）；守门退出码 %d，待验证 %d"
              % ("PASS" if ok else "FAIL", name, got_claims, expect["claims"],
                 trusted, pending, expect["trusted"], expect["pending"], guard_exit, guard_pending))
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("zh-fact-polish 确定性复现\n" + "=" * 46)
    results = [check_tests()]
    for name, exp in CASES.items():
        results.append(check_case(name, exp))
    print("=" * 46)
    if all(results):
        print("全部通过：检查部分可逐次复现。")
        print("说明：文章生成由模型完成，输出有随机性，不在本脚本复现范围内。")
        return 0
    print("存在失败项，请查看上面的输出。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
