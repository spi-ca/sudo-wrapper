#!/usr/bin/env python3
"""Non-privileged integration tests; never execute the real sudo-rs."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/main.zig"
TARGET = b'"/usr/bin/sudo-rs"'
ERROR = b""  # Silent failure was explicitly selected.


def zig(*args):
    if os.environ.get("ZIG"):
        return [os.environ["ZIG"], *args]
    if shutil.which("zig"):
        return ["zig", *args]
    return ["mise", "exec", "--", "zig", *args]


class WrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="sudo-wrapper-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.directory = Path(cls.tmp.name)
        cls.probe = cls.directory / "probe"
        c_source = cls.directory / "probe.c"
        c_source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static void number(uint32_t n) { fwrite(&n, sizeof(n), 1, stdout); }
static void strings(char **s) {
    uint32_t count = 0;
    while (s[count]) ++count;
    number(count);
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t n = (uint32_t)strlen(s[i]);
        number(n);
        fwrite(s[i], 1, n, stdout);
    }
}
int main(int argc, char **argv, char **envp) {
    if (argc == 3 && strcmp(argv[1], "--launch-empty") == 0) {
        char *args[] = {"", "--", "arg", NULL};
        execve(argv[2], args, envp);
        return 99;
    }
    if (argc == 3 && strcmp(argv[1], "--launch-noargv") == 0) {
        char *args[] = {NULL};
        execve(argv[2], args, envp);
        return 99;
    }
    number((uint32_t)getpid());
    strings(argv);
    strings(envp);
    return 37;
}
''')
        subprocess.run(zig("cc", "-O2", str(c_source), "-o", str(cls.probe)),
                       cwd=ROOT, check=True)
        subprocess.run([str(ROOT / "build.sh")], cwd=ROOT, check=True)
        cls.wrapper = cls.build_fixture(cls.probe, "working")

    @classmethod
    def build_fixture(cls, target, name):
        # Change only the compile-time literal in a private test source.
        source = SOURCE.read_bytes()
        assert source.count(TARGET) == 1
        path = os.fsencode(target)
        assert not any(c in path for c in (b'"', b'\\', b'\n'))
        test_source = cls.directory / (name + ".zig")
        test_source.write_bytes(source.replace(TARGET, b'"' + path + b'"'))
        output = cls.directory / name
        subprocess.run([str(ROOT / "build.sh"), str(test_source), str(output)],
                       cwd=ROOT, check=True)
        return output

    @staticmethod
    def decode(data):
        offset = 0

        def number():
            nonlocal offset
            n, = struct.unpack_from("<I", data, offset)
            offset += 4
            return n

        def strings():
            nonlocal offset
            result = []
            for _ in range(number()):
                length = number()
                result.append(data[offset:offset + length])
                offset += length
            return result

        result = (number(), strings(), strings())
        assert offset == len(data)
        return result

    def test_arguments_environment_pid_and_exit_status(self):
        args = ["sudo", "-u", "root", "--", "", "a b", "$(touch ignored)",
                "; echo ignored", "한글", "x" * 8192]
        env = {"PATH": str(self.directory), "LANG": "C", "KEEP": "a=b c",
               "SUDO_RS_PATH": "/not/a/target", "EMPTY": ""}
        process = subprocess.Popen(args, executable=self.wrapper, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(err, b"")
        pid, argv, environment = self.decode(out)
        self.assertEqual(pid, process.pid)
        self.assertEqual(argv, [os.fsencode(arg) for arg in args])
        self.assertEqual(environment, [os.fsencode(k + "=" + v) for k, v in env.items()])

    def test_empty_environment_and_no_extra_arguments(self):
        process = subprocess.run([str(self.wrapper)], env={}, capture_output=True,
                                 timeout=10)
        self.assertEqual(process.returncode, 37)
        _, argv, environment = self.decode(process.stdout)
        self.assertEqual(argv, [os.fsencode(self.wrapper)])
        self.assertEqual(environment, [])

    def test_sudoedit_alias_preserves_mode_name(self):
        alias = self.directory / "sudoedit"
        alias.symlink_to(self.wrapper.name)
        process = subprocess.run([str(alias), "--", "a b"], env={},
                                 capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(process.stderr, b"")
        _, argv, environment = self.decode(process.stdout)
        self.assertEqual(argv, [os.fsencode(alias), b"--", b"a b"])
        self.assertEqual(environment, [])

    def test_argv0_is_not_a_routing_or_authorization_boundary(self):
        for argv0 in [b"sudo", b"sudoedit", b"visudo", b"sudoedit-extra", b"",
                      b"name-\xff", b"x" * 8192, b"/x/sudoedit/"]:
            with self.subTest(argv0=argv0[:24]):
                if argv0:
                    process = subprocess.run([argv0, b"--", b"arg"],
                                             executable=self.wrapper, env={},
                                             capture_output=True, timeout=10)
                else:
                    # Python posix_spawn rejects empty argv[0]; the private C
                    # launcher uses execve directly to exercise the real ABI.
                    process = subprocess.run([str(self.probe), "--launch-empty",
                                              str(self.wrapper)], env={},
                                             capture_output=True, timeout=10)
                self.assertEqual(process.returncode, 37)
                self.assertEqual(process.stderr, b"")
                _, argv, _ = self.decode(process.stdout)
                self.assertEqual(argv, [argv0, b"--", b"arg"])

    def test_kernel_normalized_empty_argument_vector(self):
        process = subprocess.run([str(self.probe), "--launch-noargv", str(self.wrapper)],
                                 env={}, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(process.stderr, b"")
        _, argv, environment = self.decode(process.stdout)
        self.assertEqual(argv, [b""])
        self.assertEqual(environment, [])

    def test_visudo_has_an_independent_fixed_target(self):
        # Test the same compile-time substitution used by the production build.
        source = SOURCE.read_bytes().replace(TARGET, b'"/usr/bin/visudo-rs"')
        self.assertNotIn(TARGET, source)
        probe_alias = self.directory / "visudo-probe"
        probe_alias.symlink_to(self.probe.name)
        test_source = self.directory / "visudo.zig"
        test_source.write_bytes(source.replace(b'"/usr/bin/visudo-rs"',
                                               b'"' + os.fsencode(probe_alias) + b'"'))
        wrapper = self.directory / "visudo"
        subprocess.run([str(ROOT / "build.sh"), str(test_source), str(wrapper)],
                       cwd=ROOT, check=True)
        # A sudo-like argv[0] cannot change which executable this wrapper runs.
        process = subprocess.run(["sudo", "--", "file"], executable=wrapper,
                                 env={}, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(process.stderr, b"")
        _, argv, _ = self.decode(process.stdout)
        self.assertEqual(argv, [b"sudo", b"--", b"file"])
        trace = self.directory / "visudo.trace"
        subprocess.run(["strace", "-qq", "-b", "execve", "-o", str(trace),
                        str(wrapper), "--", "file"], capture_output=True,
                       timeout=10, check=True)
        lines = trace.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(str(probe_alias), lines[1])

    def test_failure_never_falls_back_to_shell_or_path(self):
        cases = [(self.directory / "absent", "missing"),
                 (self.directory / "not-executable", "denied"),
                 (self.directory / "invalid-executable", "invalid")]
        cases[1][0].write_text("not executable\n")
        cases[1][0].chmod(0o644)
        cases[2][0].write_text("#!/missing/interpreter\n")
        cases[2][0].chmod(0o755)
        for target, name in cases:
            with self.subTest(name=name):
                wrapper = self.build_fixture(target, name)
                result = subprocess.run([str(wrapper)], env={"PATH": "/usr/bin"},
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 127)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, ERROR)
        # ENOEXEC: executable text without a shebang must not become a shell script.
        target = self.directory / "plain-text"
        target.write_text("echo UNEXPECTED\n")
        target.chmod(0o755)
        wrapper = self.build_fixture(target, "enoexec")
        result = subprocess.run([str(wrapper)], capture_output=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (127, b"", ERROR))

    def test_elf_size_and_permissions(self):
        for name, size in [("sudo", 166), ("visudo", 168)]:
            with self.subTest(name=name):
                binary = ROOT / "zig-out/bin" / name
                data = binary.read_bytes()
                self.assertEqual(len(data), size)
                self.assertEqual(data[:7], b"\x7fELF\x02\x01\x01")
                e_type, machine = struct.unpack_from("<HH", data, 16)
                self.assertEqual((e_type, machine), (3, 62))  # ET_DYN, EM_X86_64
                phoff, shoff = struct.unpack_from("<QQ", data, 32)
                phsize, phnum = struct.unpack_from("<HH", data, 54)
                self.assertEqual(shoff, 0)
                self.assertEqual(phnum, 1)
                headers = [struct.unpack_from("<IIQQQQQQ", data, phoff + i * phsize)
                           for i in range(phnum)]
                self.assertEqual([(h[0], h[1]) for h in headers], [(1, 5)])
                self.assertEqual(headers[0][2], 0)
                self.assertEqual(headers[0][5], len(data))
                self.assertEqual(headers[0][5], headers[0][6])
                self.assertIn(os.fsencode("/usr/bin/" + name + "-rs") + b"\0", data)
                self.assertEqual(binary.stat().st_mode & 0o7777, 0o755)
        alias = ROOT / "zig-out/bin/sudoedit"
        self.assertTrue(alias.is_symlink())
        self.assertEqual(os.readlink(alias), "sudo")
        self.assertEqual(alias.resolve(), (ROOT / "zig-out/bin/sudo").resolve())

    def test_default_stack_is_non_executable(self):
        # Pause before exec to inspect the wrapper's own mappings, not the
        # backend's. Use the same source/linker and a private non-privileged target.
        source = SOURCE.read_bytes().replace(
            TARGET, b'"' + os.fsencode(self.probe) + b'"')
        instruction = b'        \\\\ pushq $59\n'
        self.assertEqual(source.count(instruction), 1)
        source = source.replace(instruction,
                                b'        \\\\ pushq $34\n'
                                b'        \\\\ popq %%rax\n'
                                b'        \\\\ syscall\n' + instruction)
        test_source = self.directory / "mapping-probe.zig"
        test_source.write_bytes(source)
        probe = self.directory / "mapping-probe"
        subprocess.run([str(ROOT / "build.sh"), str(test_source), str(probe)],
                       cwd=ROOT, check=True)
        process = subprocess.Popen([str(probe)])
        try:
            rows = (Path("/proc") / str(process.pid) / "maps").read_text().splitlines()
            stack = [row for row in rows if row.endswith("[stack]")]
            image = [row for row in rows if row.endswith(str(probe))]
            self.assertEqual(len(stack), 1, rows)
            self.assertEqual(stack[0].split()[1], "rw-p", stack)
            self.assertEqual(len(image), 1, rows)
            self.assertEqual(image[0].split()[1], "r-xp", image)
        finally:
            process.kill()
            process.wait(timeout=5)

    def test_success_has_only_execve(self):
        trace = self.directory / "success.trace"
        result = subprocess.run(["strace", "-qq", "-b", "execve", "-o", str(trace),
                                 str(self.wrapper), "--", "arg"],
                                capture_output=True, timeout=10)
        lines = trace.read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all(line.startswith("execve(") for line in lines), lines)
        self.assertIn(str(self.probe), lines[1])
        self.assertTrue(result.stdout)  # detached probe ran

    def test_failure_syscalls(self):
        wrapper = self.build_fixture(self.directory / "absent", "traced-missing")
        trace = self.directory / "failure.trace"
        result = subprocess.run(["strace", "-qq", "-o", str(trace), str(wrapper)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 127)
        self.assertEqual([line.split("(", 1)[0] for line in trace.read_text().splitlines()],
                         ["execve", "execve", "exit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
