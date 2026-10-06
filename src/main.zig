const builtin = @import("builtin");

comptime {
    if (builtin.os.tag != .linux or builtin.cpu.arch != .x86_64)
        @compileError("this entry point requires Linux x86_64");
}

// Linux x86_64 initial stack: argc, argv[], NULL, envp[], NULL, auxv[].
// No Zig startup, allocator, libc, or argument/environment rewriting.
pub export fn _start() callconv(.naked) noreturn {
    asm volatile (
    // Consume argc; balanced push/pop pairs reuse only its old stack slot.
        \\ popq %%rdx
        \\ pushq %%rsp
        \\ popq %%rsi
        \\ leaq 8(%%rsi,%%rdx,8), %%rdx
        // CALL skips the path and pushes its address; POP obtains it without
        // an absolute pointer or runtime relocation. This is not a libc call.
        \\ callq 2f
        \\ 1: .asciz "/usr/bin/sudo-rs"
        \\ 2: popq %%rdi
        \\ pushq $59
        \\ popq %%rax
        \\ syscall
        // execve returns only on failure. Silent exit(127), no fallback/retry.
        \\ pushq $60
        \\ popq %%rax
        \\ pushq $127
        \\ popq %%rdi
        \\ syscall
        // If an inherited sandbox makes exit return, trap instead of falling
        // through. Such a sandbox can change the observed termination status.
        \\ ud2
    );
}
