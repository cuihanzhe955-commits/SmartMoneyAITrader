import hashlib,json,re
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts import audit_components as audit

ROOT=Path(__file__).resolve().parents[1]


def test_published_audit_matches_exact_dependency_inputs_and_known_advisory_results():
    data=json.loads((ROOT/"docs/DEPENDENCY_AUDIT.json").read_text(encoding="utf-8"))
    assert data["requirements_sha256"]==hashlib.sha256((ROOT/"requirements.txt").read_bytes()).hexdigest()
    assert data["npm_lock_sha256"]==hashlib.sha256((ROOT/"frontend/package-lock.json").read_bytes()).hexdigest()
    assert {p["name"]:p["version"] for p in data["python"]}==audit.pins(ROOT/"requirements.txt")
    assert data["python_active_advisories"]==0 and data["npm_advisories"]["total"]==0
    assert all(p["license_files"] for p in data["python"])
    assert {p["name"]:p["version"] for p in data["research"]}==audit.pins(ROOT/"requirements-research.txt")
    assert data["research_active_advisories"]==0
    assert data["research_requirements_sha256"]==hashlib.sha256((ROOT/"requirements-research.txt").read_bytes()).hexdigest()


def test_verified_windows_wheel_lock_covers_all_production_packages():
    versions={}
    for line in (ROOT/"requirements-win-py312.lock").read_text().splitlines():
        if line.startswith("#"):continue
        m=re.fullmatch(r"([A-Za-z0-9_-]+)==([A-Za-z0-9.+_-]+) --hash=sha256:([0-9a-f]{64})",line)
        assert m,line
        versions[m[1].lower().replace("_","-")]=m[2]
    assert versions==audit.pins(ROOT/"requirements.txt")


@pytest.mark.parametrize("line",["requests>=2","--index-url https://fixture.invalid","x==1\nx==2"])
def test_audit_does_not_accept_unpinned_or_injected_requirement_options(tmp_path,line):
    p=tmp_path/"requirements.txt";p.write_text(line)
    with pytest.raises(ValueError):audit.pins(p)


def fixture(root):
    (root/"frontend").mkdir();(root/"requirements.txt").write_text("fixture==1.0\n")
    packages={"node_modules/parent":{"version":"1.0","license":"MIT","integrity":"sha512-fixture"},
              "node_modules/parent/node_modules/child":{"version":"2.0","license":"MIT","inBundle":True}}
    (root/"frontend/package-lock.json").write_text(json.dumps({"packages":packages}))
    report=root/"npm-audit.json";report.write_text(json.dumps({"vulnerabilities":{},"metadata":{"vulnerabilities":{"total":0}}}))
    return packages,report


def test_bundled_npm_dependency_uses_its_verified_parent_archive_integrity(tmp_path):
    packages,report=fixture(tmp_path)
    with patch.object(audit,"ROOT",tmp_path),patch.object(audit,"pypi",side_effect=lambda p:dict(name=p[0],version=p[1],vulnerabilities=[])):
        data=audit.audit(report)
    child=data["npm"][1]
    assert child["integrity_source"]=="node_modules/parent" and child["integrity"]=="sha512-fixture"


@pytest.mark.parametrize("field",["integrity","version","license"])
def test_missing_supply_chain_evidence_is_not_reported_as_passed(tmp_path,field):
    packages,report=fixture(tmp_path);del packages["node_modules/parent"][field]
    (tmp_path/"frontend/package-lock.json").write_text(json.dumps({"packages":packages}))
    with patch.object(audit,"ROOT",tmp_path),patch.object(audit,"pypi",return_value={"vulnerabilities":[]}):
        with pytest.raises(ValueError):audit.audit(report)


def evidence():
    files={"requirements.txt":b"fixture==1\n","requirements-research.txt":b"reference==1\n","frontend/package-lock.json":b"{}"}
    report={key:hashlib.sha256(files[path]).hexdigest() for path,key in (("requirements.txt","requirements_sha256"),("requirements-research.txt","research_requirements_sha256"),("frontend/package-lock.json","npm_lock_sha256"))}
    report.update(python_active_advisories=0,research_active_advisories=0,npm_advisories={"total":0})
    files["docs/DEPENDENCY_AUDIT.json"]=json.dumps(report).encode()
    return files


@pytest.mark.parametrize("path",["requirements.txt","requirements-research.txt","frontend/package-lock.json"])
def test_export_refuses_stale_component_audit_after_dependency_change(path):
    from scripts.build_source_package import verify_component_audit
    files=evidence();assert verify_component_audit(files)
    files[path]+=b" ";
    with pytest.raises(ValueError,match="当前依赖清单"):verify_component_audit(files)


@pytest.mark.parametrize("value",[1,None,False,"0"])
def test_export_does_not_accept_missing_or_nonzero_vulnerability_evidence(value):
    from scripts.build_source_package import verify_component_audit
    files=evidence();r=json.loads(files["docs/DEPENDENCY_AUDIT.json"]);r["python_active_advisories"]=value
    files["docs/DEPENDENCY_AUDIT.json"]=json.dumps(r).encode()
    with pytest.raises(ValueError,match="未关闭项或结果无效"):verify_component_audit(files)
