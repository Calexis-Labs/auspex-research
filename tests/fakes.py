"""Ag'a dokunmayan sahte driver/runner'lar — "ret, ag I/O'sundan ONCE olur" kanitinin araci."""

from dataclasses import dataclass, field


@dataclass
class FakeResponse:
    result: str


@dataclass
class FakeDriver:
    """scrapli driver'inin testte kullanilan yuzeyi: open/close/send_command."""

    outputs: dict[str, str] = field(default_factory=dict)
    default_output: str = "{}"
    sent: list[str] = field(default_factory=list)
    opened: bool = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def send_command(self, command: str) -> FakeResponse:
        if not self.opened:
            raise RuntimeError("driver acilmadan komut gonderildi")
        self.sent.append(command)
        return FakeResponse(self.outputs.get(command, self.default_output))


@dataclass
class FakeRunner:
    """HostExecTransport'un subprocess runner'i yerine gecer: argv listesini kaydeder."""

    outputs: dict[str, str] = field(default_factory=dict)
    default_output: str = "{}"
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        return self.outputs.get(" ".join(argv), self.default_output)
