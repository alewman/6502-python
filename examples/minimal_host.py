"""The smallest complete host: 64 KiB of RAM and a three-instruction program."""

from sixfiveohtwo import MOS6502


def main() -> None:
    memory = bytearray(0x10000)
    cpu = MOS6502(memory.__getitem__, memory.__setitem__)  # read_byte, write_byte

    # LDA #$2A; CLC; ADC #$10 leaves A holding $3A.
    memory[0x8000:0x8005] = bytes((0xA9, 0x2A, 0x18, 0x69, 0x10))
    memory[0xFFFC:0xFFFE] = bytes((0x00, 0x80))  # the reset vector
    cpu.request_reset()

    cycles = cpu.step()  # the reset sequence: seven cycles, PC from $FFFC
    for _ in range(3):
        cycles += cpu.step()

    print(f"A={cpu.a:02X} PC={cpu.pc:04X} cycles={cycles}")


if __name__ == "__main__":
    main()
