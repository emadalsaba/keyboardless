"""Streaming commit engine: turns Vosk partial results into text that is safe to
inject *while the user is still speaking*.

Why this exists
---------------
Vosk emits a growing ``partial`` string several times per second. Naively typing
each partial would require deleting half of it a moment later, because the tail
of a partial result changes as more audio arrives ("الجاي" -> "الجي" -> ...).

The fix is the same trick used by whisper-streaming: only words confirmed by two
consecutive hypotheses (a LocalAgreement-2 rule) are considered stable, and even
then the last stable word is held back because it is the one most likely to be
rewritten. Everything after that point stays "pending" and is not typed yet.

The engine therefore maintains three views:
    committed  -- words that have survived agreement, i.e. safe to type
    pending    -- words still in flux (shown in the overlay, never typed)
    injected   -- what this app has already typed into the focused window

``update()`` returns a list of edit operations to apply to the target window so
that ``injected`` converges on ``committed`` (insertions and backspace-repairs),
plus the current pending tail for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def common_prefix_len(a: list[str], b: list[str]) -> int:
    """Length of the shared leading run of two word lists."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


@dataclass
class Edit:
    """A minimal change to apply to the focused window."""

    delete_words: int = 0
    insert_text: str = ""

    def is_empty(self) -> bool:
        return self.delete_words == 0 and not self.insert_text


@dataclass
class CommitEngine:
    """LocalAgreement-2 streaming committer.

    Parameters
    ----------
    min_agree:
        How many consecutive hypotheses must agree on a word before it is
        committed. 2 is the value used by whisper-streaming and is what keeps
        latency low without injecting text that gets corrected a beat later.
    hold_back:
        When true (1), the *last* token of a hypothesis is never committed while
        it is last, no matter how often it agrees. The trailing token of a
        partial result is the one most likely to still be half-spoken ("الم" of
        "المتبقي"), so it waits for the next hypothesis to confirm it.
    """

    min_agree: int = 2
    hold_back: int = 1

    committed: list[str] = field(default_factory=list)
    injected: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    _prev_hyp: list[str] = field(default_factory=list)
    _agree_run: list[int] = field(default_factory=list)  # per-index agreement streak

    # ---------------------------------------------------------------- internals
    def _rewind_committed_against(self, hyp: list[str]) -> None:
        """Drop committed words the recognizer has since rewritten.

        Vosk occasionally revises the tail of a segment when it finalises it
        (``Result()``). If the new hypothesis disagrees with what we already
        typed, the typed words must go back into flux so ``update()`` can emit
        the necessary backspaces instead of leaving wrong text on screen.

        A hypothesis that is merely *shorter* than what is committed proves
        nothing (it is just the trailing token being held back), so the
        committed prefix is only truncated on a genuine disagreement.
        """
        keep = common_prefix_len(self.committed, hyp)
        if keep < len(self.committed) and keep < len(hyp):
            del self.committed[keep:]

    def _promote(self, hyp: list[str]) -> None:
        """Commit words whose agreement streak reached ``min_agree``."""
        run = self._agree_run
        if len(run) < len(hyp):
            run.extend([0] * (len(hyp) - len(run)))
        else:
            del run[len(hyp):]

        for i, word in enumerate(hyp):
            if i < len(self.committed) and self.committed[i] == word:
                continue  # already committed
            # A word agreeing with the previous hypothesis advances its streak.
            if i < len(self._prev_hyp) and self._prev_hyp[i] == word:
                run[i] += 1
            else:
                run[i] = 1
            if run[i] >= self.min_agree:
                # Commit in order: only extend, and never skip a gap.
                if i == len(self.committed):
                    self.committed.append(word)

    def _diff(self) -> Edit:
        """Edit that makes the target window match ``committed``."""
        keep = common_prefix_len(self.injected, self.committed)
        delete_words = len(self.injected) - keep
        new_words = self.committed[keep:]
        self.injected = list(self.committed)
        return Edit(delete_words=delete_words, insert_text=" ".join(new_words))

    # ------------------------------------------------------------------- public
    def update(self, hypothesis: str, *, final: bool = False) -> tuple[Edit, list[str]]:
        """Feed one hypothesis; return the window edit and the pending tail.

        ``final=True`` means the utterance is closed (silence detected or the
        user stopped dictation): everything the recognizer produced is then
        committed, including the trailing token it was holding back.
        """
        hyp = hypothesis.split()
        if final or not self.hold_back or len(hyp) <= 1:
            effective = hyp
        else:
            effective = hyp[:-1]  # trailing token may still be half-spoken

        self._rewind_committed_against(effective)
        self._promote(effective)

        if final and hyp:
            # Nothing may stay in flux once the utterance is closed. An *empty*
            # final (Vosk closes a segment on a noise burst, `Result()` -> "")
            # must not overwrite what is committed: an empty hypothesis proves
            # nothing, and clearing it here would backspace the whole line.
            self.committed = list(hyp)

        self.pending = hyp[len(self.committed):]
        self._prev_hyp = effective
        return self._diff(), self.pending

    def seal_segment(self) -> None:
        """Close the current segment for good -- what follows is a *continuation*.

        Vosk reports a pause by finishing the utterance: the next ``partial`` it
        emits contains only the new words. Without sealing, those words look to
        :meth:`update` like the recognizer rewording the entire segment, because
        ``common_prefix_len`` against the previous segment is 0 -- so it emits
        backspaces for everything already typed and replaces the sentence.

        Measured on the user's machine (2026-09): "say a full sentence, pause,
        say the next one" erased the first sentence and typed only the second.

        Sealing clears the internal view *without touching the target window*:
        the text on screen stays, the new segment is compared against nothing,
        and it is appended after the segment's closing separator.
        """
        self.committed.clear()
        self.injected.clear()
        self.pending.clear()
        self._prev_hyp.clear()
        self._agree_run.clear()

    def reset(self) -> None:
        self.committed.clear()
        self.injected.clear()
        self.pending.clear()
        self._prev_hyp.clear()
        self._agree_run.clear()
