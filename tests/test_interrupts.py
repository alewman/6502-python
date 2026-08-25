import pytest

from sixfiveohtwo import InterruptBoundary, InterruptLines


def test_reset_and_irq_are_level_sensitive_at_instruction_boundaries():
    lines = InterruptLines(reset=True, irq=True)

    assert lines.sample_instruction_boundary() == InterruptBoundary(
        reset=True, irq=True, nmi=False
    )
    assert lines.sample_instruction_boundary() == InterruptBoundary(
        reset=True, irq=True, nmi=False
    )

    lines.set_reset(False)
    lines.set_irq(False)
    assert lines.sample_instruction_boundary() == InterruptBoundary(
        reset=False, irq=False, nmi=False
    )


def test_nmi_latches_rising_edge_and_is_consumed_by_sampling():
    lines = InterruptLines()

    lines.set_nmi(True)
    assert lines.sample_instruction_boundary() == InterruptBoundary(
        reset=False, irq=False, nmi=True
    )
    assert lines.sample_instruction_boundary() == InterruptBoundary(
        reset=False, irq=False, nmi=False
    )

    lines.set_nmi(False)
    lines.set_nmi(True)
    assert lines.sample_instruction_boundary().nmi is True


def test_nmi_high_level_does_not_retrigger_without_a_new_rising_edge():
    lines = InterruptLines(nmi=True)

    assert lines.sample_instruction_boundary().nmi is False
    assert lines.sample_instruction_boundary().nmi is False


def test_signal_nmi_latches_a_pending_signal():
    lines = InterruptLines()

    lines.signal_nmi()

    assert lines.nmi_pending is True
    assert lines.sample_instruction_boundary().nmi is True
    assert lines.nmi_pending is False


@pytest.mark.parametrize("method", ["set_reset", "set_irq", "set_nmi"])
def test_line_drivers_require_boolean_levels(method):
    with pytest.raises(TypeError):
        getattr(InterruptLines(), method)(1)
