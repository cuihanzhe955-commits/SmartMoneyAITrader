import hashlib
import io
import json
import zipfile
from pathlib import Path
import pytest
from scripts.build_source_package import allowed, scan_content, build


@pytest.mark.parametrize("path", ["runtime/credentials.dpapi","runtime/terminal.db","runtime/.env",
    ".env","frontend/node_modules/foo.js","docs/phaseC_baseline.json","tests/screenshots/private.png"])
def test_package_excludes_private_and_local_artifacts(path):
    assert not allowed(path)


@pytest.mark.parametrize("text", ["sk-" + "x"*32, "ghp_" + "x"*32, "ou_" + "x"*32,
    "-----BEGIN " + "PRIVATE KEY-----", "C:" + chr(92) + "Users" + chr(92) + "private-person" + chr(92)])
def test_sensitive_patterns_refuse_known_shapes(text):
    assert scan_content("sample.txt",text.encode())


def minimal(root):
    entries={
        "terminal/api.py":b"pass",
        "frontend/dist/index.html":b"<title>fixture</title>",
        "frontend/package-lock.json":b"{}",
        ".gitignore":b"runtime/",
        "runtime/credentials.dpapi":b"private-test-fixture",
        ".env":b"private-test-fixture",
    }
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as z:z.writestr("sample.csv","1,2,3\n")
    entries["data/BTCUSDT-1m-2024-08-05.zip"]=buffer.getvalue()
    for name,data in entries.items():
        p=root/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)


def test_built_zip_is_scanned_and_manifest_matches(tmp_path):
    root=tmp_path/"source"; minimal(root)
    result=build(root,tmp_path/"export")
    z=zipfile.ZipFile(result["archive"])
    assert not any("runtime/" in n or n.endswith("/.env") for n in z.namelist())
    manifest=json.loads(z.read("SmartMoneyAITrader/SOURCE_MANIFEST.json"))
    assert manifest["stable"] is False and manifest["sensitive_scan"]["matches"] == 0
    for name,sha in manifest["files"].items():
        assert hashlib.sha256(z.read("SmartMoneyAITrader/"+name)).hexdigest()==sha
    assert hashlib.sha256(Path(result["archive"]).read_bytes()).hexdigest()==result["sha256"]


def test_package_secrets_abort_before_writing(tmp_path):
    root=tmp_path/"source"; minimal(root)
    (root/"terminal/api.py").write_text('token="' + "sk-" + "x"*32 + '"')
    with pytest.raises(ValueError,match="敏感信息扫描未通过"): build(root,tmp_path/"export")
    assert not (tmp_path/"export").exists()


def test_package_will_not_overwrite_or_export_inside_source(tmp_path):
    root=tmp_path/"source"; minimal(root)
    with pytest.raises(ValueError,match="主工程之外"): build(root,root/"export")
    out=tmp_path/"existing";out.mkdir()
    with pytest.raises(ValueError,match="拒绝覆盖"):build(root,out)
