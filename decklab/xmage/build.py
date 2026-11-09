"""Explicit compilation against the pinned official XMage release; read-only discovery."""
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

VERSION = "1.4.63-dev (2026-10-31 09-42)"
SOURCE_REVISION = "79aec614fc29d0c3eebd10fff0d5c1b40852bd52"
RELEASE_URL = ("https://github.com/magefree/mage/releases/download/xmage_1.4.63V1/"
               "mage-full_1.4.63-dev_2026-10-31_09-42.zip")
RELEASE_SHA256 = "f48e69a2583720800ab6a447458ede73bded5cb21905b0d9658a6052ab43908a"
# SHA256 of sorted relative jar paths, NUL, each file's SHA256, LF (all 86 server jars).
ENGINE_SHA256 = "596c4ca03d3be39230714bf28672543d30109c9c8eb8396d6f0ecdec20a67805"
JAVA_SOURCE = Path(__file__).with_name("Bridge.java")
RUNTIME_POLICY = "MAD/6/threads1/heap1024/activeProcessor1/London/0/casual20/commander40/21"


def _sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _server(home):
    if not home:
        raise ValueError("XMage is not configured.")
    root = Path(home).resolve()
    for candidate in (root, root / "mage-server", root / "xmage" / "mage-server"):
        if (candidate / "lib" / "mage-1.4.63.jar").is_file():
            return candidate
    raise ValueError("The configured XMage folder has no supported server release.")


def _engine_sha(home):
    entries = sorted((f.relative_to(home).as_posix(), _sha(f))
                     for directory in ("lib", "plugins")
                     for f in (home / directory).glob("*.jar"))
    return hashlib.sha256("".join(f"{name}\0{sha}\n" for name, sha in entries).encode()).hexdigest()


def _build_dir(value):
    if value is None:
        from decklab.lib.config import DATA
        value = DATA / "xmage" / "bridge"
    return Path(value).resolve()


def _java(value=None):
    from decklab.lib.forge.install import find_java
    if value is None:
        from decklab.lib import config
        value = config.load().get("forge_java")
    found = find_java(value)
    if found is None:
        raise ValueError("A full Java installation was not found.")
    return Path(found).resolve()


def _runtime_facts(java, source_sha, artifact_sha):
    java_sha = _sha(java)
    release_sha = _sha(java.parent.parent / "release")
    identity = hashlib.sha256(("decklab-xmage-v1\n" + ENGINE_SHA256 + "\n" + source_sha + "\n"
                               + artifact_sha + "\n" + java_sha + "\n" + release_sha + "\n"
                               + RUNTIME_POLICY + "\n").encode()).hexdigest()
    return {"identity_sha256": identity, "java_sha256": java_sha,
            "java_release_sha256": release_sha}


def _command(java, home, artifact, artifact_sha, identity):
    separator = os.pathsep
    classpath = separator.join((str(artifact), str(home / "lib" / "*"),
                               str(home / "plugins" / "*")))
    return [str(java), "-Xmx1024m", "-XX:ActiveProcessorCount=1", "-Djava.awt.headless=true",
            "-Dxmage.dataCollectors.printGameLogs=false",
            "-Dxmage.dataCollectors.saveGameHistory=false",
            f"-Ddecklab.xmage.home={home}", f"-Ddecklab.xmage.engine_sha256={ENGINE_SHA256}",
            f"-Ddecklab.xmage.bridge_sha256={artifact_sha}",
            f"-Ddecklab.xmage.source_sha256={_sha(JAVA_SOURCE)}",
            f"-Ddecklab.xmage.identity_sha256={identity}",
            "-cp", classpath, "decklab.xmage.Bridge"]


def describe(home=None, *, build_dir=None, java=None):
    """Return verified readiness and a private direct-JVM argv, without compiling or running."""
    result = {"ready": False, "problem": "XMage is not configured.", "version": VERSION,
              "source_revision": SOURCE_REVISION, "engine_sha256": ENGINE_SHA256,
              "reproducible": False, "formats": ["casual", "commander"],
              "ai": "MAD skill 6; one simulation thread", "heap_mb": 1024}
    try:
        if home is None:
            from decklab.lib import config
            home = config.load().get("xmage_dir")
        server = _server(home)
        if _engine_sha(server) != ENGINE_SHA256:
            raise ValueError("XMage's installed jars differ from the qualified release.")
        output = _build_dir(build_dir)
        metadata = json.loads((output / "command.json").read_text(encoding="utf-8"))
        artifact = output / "decklab-xmage.jar"
        source_sha = _sha(JAVA_SOURCE)
        artifact_sha = _sha(artifact)
        if (type(metadata.get("schema")) is not int or metadata.get("schema") != 1
                or metadata.get("source_sha256") != source_sha
                or metadata.get("engine_sha256") != ENGINE_SHA256
                or metadata.get("bridge_sha256") != artifact_sha
                or metadata.get("home") != str(server)):
            raise ValueError("XMage's bridge is stale or changed; build it explicitly again.")
        runtime = _java(java)
        facts = _runtime_facts(runtime, source_sha, artifact_sha)
        result.update(ready=True, problem=None, bridge_sha256=artifact_sha,
                      bridge_source_sha256=source_sha, source_sha256=source_sha,
                      **facts, command=_command(runtime, server, artifact, artifact_sha,
                                                facts["identity_sha256"]))
    except FileNotFoundError:
        result["problem"] = "XMage's bridge has not been built for this installation."
    except (OSError, ValueError, TypeError, AttributeError):
        # No local paths, card lists or raw native exceptions in API-facing status.
        result["problem"] = ("XMage's installation or bridge could not be verified. "
                             "Check the pinned release and build the bridge explicitly.")
    return result


def build(home, *, build_dir=None, java=None):
    """Compile only our Java source; never change upstream files or launch an XMage server."""
    server = _server(home)
    if _engine_sha(server) != ENGINE_SHA256:
        raise ValueError("XMage's installed jars differ from the pinned official release.")
    runtime = _java(java)
    compiler = runtime.with_name("javac.exe" if os.name == "nt" else "javac")
    if not compiler.is_file():
        raise ValueError("Building the XMage bridge requires a JDK with javac.")
    output = _build_dir(build_dir)
    output.mkdir(parents=True, exist_ok=True)
    classpath = os.pathsep.join((str(server / "lib" / "*"), str(server / "plugins" / "*")))
    with tempfile.TemporaryDirectory(prefix="decklab-xmage-build-") as temporary:
        classes = Path(temporary) / "classes"
        classes.mkdir()
        source = Path(temporary) / "Bridge.java"
        source_bytes = JAVA_SOURCE.read_bytes()
        source.write_bytes(source_bytes)
        compiled = subprocess.run([str(compiler), "--release", "17", "-encoding", "UTF-8",
                                   "-cp", classpath, "-d", str(classes), str(source)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
        if compiled.returncode:
            raise ValueError("The XMage bridge did not compile: " + compiled.stderr[-4000:])
        staged = output / "decklab-xmage.jar.tmp"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(classes.rglob("*.class")):
                info = zipfile.ZipInfo(path.relative_to(classes).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        artifact = output / "decklab-xmage.jar"
        staged.replace(artifact)
    metadata = {"schema": 1, "home": str(server), "version": VERSION,
                "source_revision": SOURCE_REVISION, "engine_sha256": ENGINE_SHA256,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(), "bridge_sha256": _sha(artifact)}
    staged_metadata = output / "command.json.tmp"
    staged_metadata.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    staged_metadata.replace(output / "command.json")
    return describe(server, build_dir=output, java=runtime)
