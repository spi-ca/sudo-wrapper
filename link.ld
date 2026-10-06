/* Standard ELF64 static PIE: one read/execute mapping, no GNU_STACK header.
 * Relies on modern NX-capable Linux x86_64 default non-executable stacks.
 * All addresses are position-independent; no runtime relocation is needed. */
ENTRY(_start)
PHDRS {
    image PT_LOAD FILEHDR PHDRS FLAGS(5);
}
SECTIONS {
    . = SIZEOF_HEADERS;
    .text : { *(.text .text.*) } :image
    .rodata : { *(.rodata .rodata.*) } :image
    .data : { *(.data .data.*) *(.got .got.*) } :image
    .bss : { *(.bss .bss.*) *(COMMON) } :image
    .relocations : { *(.rela .rela.*) *(.rel .rel.*) } :image
    ASSERT(SIZEOF(.data) == 0, "writable data is not supported")
    ASSERT(SIZEOF(.bss) == 0, "zero-initialized data is not supported")
    ASSERT(SIZEOF(.relocations) == 0, "runtime relocations are not supported")
    /DISCARD/ : {
        *(.dynamic .dynsym .dynstr .gnu.hash .hash)
        *(.comment .note .note.* .eh_frame .eh_frame_hdr)
    }
}
