from dataclasses import dataclass


@dataclass(frozen=True)
class JobTiming:
    start: float   # seconds since the run began
    end: float

    def overlaps(self, other: "JobTiming") -> bool:
        return self.start < other.end and other.start < self.end


def format_timeline(timeline: dict[str, JobTiming], width: int = 40) -> str:
    """Text bar chart of when each job ran."""
    if not timeline:
        return "(no jobs ran)"
    total = max(t.end for t in timeline.values()) or 1e-9
    lines = []
    for job, t in sorted(timeline.items(), key=lambda kv: kv[1].start):
        a = min(int(t.start / total * width), width - 1)
        b = max(a + 1, int(t.end / total * width))
        bar = " " * a + "█" * (b - a)
        lines.append(f"{job:<10} |{bar:<{width}}| {t.start:6.2f}s → {t.end:6.2f}s")
    return "\n".join(lines)