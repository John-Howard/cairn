from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn.models.base import AuditedBase
from cairn.models.config import User
from cairn.models.enums import IntakeAnswerKind, IntakeQuestionSet, IntakeStatus
from cairn.models.vocab import BusinessFunction


class IntakeQuestion(AuditedBase):
    """One question of the information-audit intake screen.

    The question set is configuration, not code (Intake & Pilot Plan §2): wording,
    hints, ordering and choice options live here per sector pack. The `populates`
    key names the field-mapping handler in cairn.intake — semantics stay in code.
    """

    __tablename__ = "intake_question"

    code: Mapped[str] = mapped_column(unique=True)
    question_set: Mapped[IntakeQuestionSet] = mapped_column(default=IntakeQuestionSet.ACTIVITY)
    section: Mapped[str]
    section_title: Mapped[str]
    order: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text)
    answer_kind: Mapped[IntakeAnswerKind]
    options: Mapped[dict | None] = mapped_column(JSON)
    # Conditional logic (configuration, like wording): {"question": code,
    # "in": [values]} or {"all": [conditions...]}. Unmet → the question is
    # not asked and any answer is normalised to not-applicable on save.
    depends_on: Mapped[dict | None] = mapped_column(JSON)
    populates: Mapped[str | None]
    enforcement_only: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class IntakeSubmission(AuditedBase):
    """One intake wizard run — produces one draft Processing Activity on submit."""

    __tablename__ = "intake_submission"

    subject_name: Mapped[str]
    question_set: Mapped[IntakeQuestionSet] = mapped_column(default=IntakeQuestionSet.ACTIVITY)
    business_function_id: Mapped[str] = mapped_column(ForeignKey("business_function.id"))
    respondent_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    respondent_contact: Mapped[str | None]
    status: Mapped[IntakeStatus] = mapped_column(default=IntakeStatus.IN_PROGRESS)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("processing_activity.id"))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("information_asset.id"))

    business_function: Mapped[BusinessFunction] = relationship()
    respondent: Mapped[User] = relationship(foreign_keys=[respondent_id])
    gaps: Mapped[list[IntakeGap]] = relationship(back_populates="submission")


class IntakeGap(AuditedBase):
    """An explicit "don't know" recorded during intake, for IG follow-up."""

    __tablename__ = "intake_gap"

    submission_id: Mapped[str] = mapped_column(ForeignKey("intake_submission.id"))
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("processing_activity.id"))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("information_asset.id"))
    question_code: Mapped[str]
    question_text: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(default=False)
    resolution_note: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[IntakeSubmission] = relationship(back_populates="gaps")
