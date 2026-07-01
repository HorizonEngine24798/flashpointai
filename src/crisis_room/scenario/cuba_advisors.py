from __future__ import annotations

from crisis_room.state.advisors import AdvisorBelief, AdvisorCouncilState, AdvisorState


def initial_us_excomm_advisor_council() -> AdvisorCouncilState:
    return AdvisorCouncilState(
        player_entity_id="us_excomm",
        advisors={
            "state": AdvisorState(
                advisor_id="state",
                name="State",
                portfolio="Diplomacy and alliance signaling",
                personality="Measured, legalistic, face-saving, sensitive to alliance politics.",
                institutional_orientation="Diplomatic settlement through credible restraint.",
                trust_player=0.62,
                trust_channels={
                    "backchannel": 0.75,
                    "private_diplomatic": 0.82,
                    "public": 0.55,
                    "military": 0.35,
                    "intel": 0.58,
                },
                paranoia=0.38,
                urgency=0.42,
                corruption=0.08,
                institutional_confidence=0.7,
                beliefs={
                    "face_saving": AdvisorBelief(
                        topic="face_saving",
                        value=0.74,
                        summary="Moscow needs a withdrawal path that does not look like public humiliation.",
                        confidence=0.64,
                    )
                },
            ),
            "defense": AdvisorState(
                advisor_id="defense",
                name="Defense",
                portfolio="Military posture and operational readiness",
                personality="Direct, impatient with ambiguity, focused on credible force.",
                institutional_orientation="Use bounded military pressure to keep initiative.",
                trust_player=0.56,
                trust_channels={
                    "military": 0.85,
                    "intel": 0.68,
                    "public": 0.58,
                    "backchannel": 0.34,
                    "private_diplomatic": 0.44,
                },
                paranoia=0.52,
                urgency=0.76,
                corruption=0.05,
                institutional_confidence=0.74,
                beliefs={
                    "delay_risk": AdvisorBelief(
                        topic="delay_risk",
                        value=0.78,
                        summary="Delay may let missile sites become operational and narrow later options.",
                        confidence=0.66,
                    )
                },
            ),
            "intelligence": AdvisorState(
                advisor_id="intelligence",
                name="Intelligence",
                portfolio="Reconnaissance, uncertainty, and adversary intent",
                personality="Skeptical, detail-oriented, wary of false certainty.",
                institutional_orientation="Reduce uncertainty before irreversible choices.",
                trust_player=0.58,
                trust_channels={
                    "intel": 0.88,
                    "backchannel": 0.55,
                    "private_diplomatic": 0.5,
                    "public": 0.4,
                    "military": 0.52,
                },
                paranoia=0.72,
                urgency=0.57,
                corruption=0.03,
                institutional_confidence=0.62,
                beliefs={
                    "command_control": AdvisorBelief(
                        topic="command_control",
                        value=0.62,
                        summary="Local Cuban and Soviet command discipline is a serious uncertainty.",
                        confidence=0.58,
                    )
                },
            ),
            "political": AdvisorState(
                advisor_id="political",
                name="Political",
                portfolio="Domestic legitimacy and public coalition management",
                personality="Pragmatic, reputation-aware, anxious about leaks and public reversals.",
                institutional_orientation="Maintain domestic support without closing private options.",
                trust_player=0.54,
                trust_channels={
                    "public": 0.78,
                    "private_diplomatic": 0.54,
                    "backchannel": 0.42,
                    "military": 0.5,
                    "intel": 0.47,
                },
                paranoia=0.56,
                urgency=0.61,
                corruption=0.18,
                institutional_confidence=0.58,
                beliefs={
                    "public_alarm": AdvisorBelief(
                        topic="public_alarm",
                        value=0.58,
                        summary="The public can tolerate pressure if the administration explains the stakes.",
                        confidence=0.6,
                    )
                },
            ),
            "legal_un": AdvisorState(
                advisor_id="legal_un",
                name="Legal/UN",
                portfolio="International law, UN posture, and legitimacy optics",
                personality="Cautious, procedural, sensitive to precedent and neutral opinion.",
                institutional_orientation="Build legitimacy before visible coercion.",
                trust_player=0.6,
                trust_channels={
                    "public": 0.72,
                    "private_diplomatic": 0.64,
                    "backchannel": 0.52,
                    "military": 0.28,
                    "intel": 0.46,
                },
                paranoia=0.44,
                urgency=0.48,
                corruption=0.04,
                institutional_confidence=0.69,
                beliefs={
                    "legitimacy": AdvisorBelief(
                        topic="legitimacy",
                        value=0.7,
                        summary="OAS and UN framing can make pressure look controlled rather than unilateral.",
                        confidence=0.63,
                    )
                },
            ),
        },
    )
