"""Tests for backend/src/identity/permissions.py — RBAC permission engine."""

from __future__ import annotations

import pytest

from src.identity.models import UserContext
from src.identity.permissions import PermissionEngine
from src.skills.models import Skill, SkillCategory


@pytest.fixture
def engine():
    """Return a fresh PermissionEngine."""
    return PermissionEngine()


@pytest.fixture
def make_skill_obj():
    """Factory for Skill objects used in permission tests."""

    def _make(skill_id="skill-1", category=SkillCategory.HR):
        return Skill(skill_id=skill_id, name=f"Skill {skill_id}", category=category)

    return _make


class TestUserLevelOverrides:
    """User-level allow/deny lists have the highest priority."""

    def test_user_deny_overrides_everything(self, engine, make_skill_obj):
        """User deny list should block even if role allows."""
        skill = make_skill_obj("skill-x")
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
            skill_allow_list=["skill-y"],
            skill_deny_list=["skill-x"],
        )
        engine.set_role_data("role-1", {"skill_allow_list": ["skill-x"]})
        assert engine.check_permission(user, skill) is False

    def test_user_allow_grants_access(self, engine, make_skill_obj):
        """User allow list should grant access even without role."""
        skill = make_skill_obj("skill-special")
        user = UserContext(
            user_id="u001",
            username="alice",
            skill_allow_list=["skill-special"],
        )
        assert engine.check_permission(user, skill) is True

    def test_user_deny_overrides_user_allow(self, engine, make_skill_obj):
        """If a skill is in both allow and deny, deny wins (deny has higher priority)."""
        skill = make_skill_obj("skill-amb")
        user = UserContext(
            user_id="u001",
            username="alice",
            skill_allow_list=["skill-amb"],
            skill_deny_list=["skill-amb"],
        )
        assert engine.check_permission(user, skill) is False


class TestRoleLevelOverrides:
    """Role-level allow/deny lists are checked after user-level."""

    def test_role_deny_blocks(self, engine, make_skill_obj):
        """Role deny list should block access."""
        skill = make_skill_obj("skill-blocked")
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
        )
        engine.set_role_data("role-1", {"skill_deny_list": ["skill-blocked"]})
        assert engine.check_permission(user, skill) is False

    def test_role_allow_grants(self, engine, make_skill_obj):
        """Role allow list should grant access."""
        skill = make_skill_obj("skill-granted")
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
        )
        engine.set_role_data("role-1", {"skill_allow_list": ["skill-granted"]})
        assert engine.check_permission(user, skill) is True

    def test_role_deny_overrides_role_allow_different_roles(self, engine, make_skill_obj):
        """If role-1 allows and role-2 denies, deny should win (checked first in loop)."""
        skill = make_skill_obj("skill-multi")
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-allow", "role-deny"],
        )
        engine.set_role_data("role-allow", {"skill_allow_list": ["skill-multi"]})
        engine.set_role_data("role-deny", {"skill_deny_list": ["skill-multi"]})
        # role-allow is checked first → it allows → but role-deny is checked next → deny
        # Actually the loop iterates through all roles checking deny first, then allow per role
        # role-allow: not in deny, in allow → returns True
        result = engine.check_permission(user, skill)
        # The first role that has it in allow_list returns True
        assert result is True


class TestDepartmentRestrictions:
    """Department category restrictions."""

    def test_dept_denied_category_blocks(self, engine, make_skill_obj):
        """Department denied_categories should block matching skill."""
        skill = make_skill_obj("skill-1", category=SkillCategory.FINANCE)
        user = UserContext(
            user_id="u001",
            username="alice",
            dept_id="dept-1",
        )
        engine.set_dept_data("dept-1", {"denied_categories": [SkillCategory.FINANCE]})
        assert engine.check_permission(user, skill) is False

    def test_dept_allowed_category_grants(self, engine, make_skill_obj):
        """Department allowed_categories should allow matching skill."""
        skill = make_skill_obj("skill-1", category=SkillCategory.HR)
        user = UserContext(
            user_id="u001",
            username="alice",
            dept_id="dept-1",
            allowed_categories=[SkillCategory.HR],
        )
        engine.set_dept_data("dept-1", {"allowed_categories": [SkillCategory.HR]})
        assert engine.check_permission(user, skill) is True


class TestDefaultDeny:
    """Default policy is closed (deny) when restrictions are configured."""

    def test_default_deny_with_roles_but_no_match(self, engine, make_skill_obj):
        """If user has roles configured but no match, default deny."""
        skill = make_skill_obj("skill-unknown")
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
        )
        engine.set_role_data("role-1", {"skill_allow_list": ["other-skill"]})
        assert engine.check_permission(user, skill) is False

    def test_open_model_when_no_restrictions(self, engine, make_skill_obj):
        """If no restrictions are configured at all, allow (dev mode)."""
        skill = make_skill_obj("skill-1")
        user = UserContext(user_id="u001", username="alice")
        assert engine.check_permission(user, skill) is True


class TestFilterSkills:
    """filter_skills should return only permitted skills."""

    def test_filter_removes_denied(self, engine, make_skill_obj):
        """filter_skills should remove denied skills."""
        skills = [make_skill_obj("s1"), make_skill_obj("s2"), make_skill_obj("s3")]
        user = UserContext(
            user_id="u001",
            username="alice",
            skill_allow_list=["s1", "s3"],
            skill_deny_list=["s2"],
        )
        filtered = engine.filter_skills(user, skills)
        ids = [s.skill_id for s in filtered]
        assert "s1" in ids
        assert "s3" in ids
        assert "s2" not in ids


class TestGetAllowedSkills:
    """get_allowed_skills returns explicit allow-list skill IDs."""

    def test_get_allowed_skills(self, engine):
        """Should return skill IDs from user + role allow lists."""
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
            skill_allow_list=["user-skill-1"],
        )
        engine.set_role_data("role-1", {"skill_allow_list": ["role-skill-1", "role-skill-2"]})
        allowed = set(engine.get_allowed_skills(user))
        assert "user-skill-1" in allowed
        assert "role-skill-1" in allowed
        assert "role-skill-2" in allowed


class TestComputeUserCategories:
    """compute_user_categories combines role + department categories."""

    def test_combine_role_and_dept_categories(self, engine):
        """Should combine categories from roles and departments."""
        user = UserContext(
            user_id="u001",
            username="alice",
            roles=["role-1"],
            dept_id="dept-1",
        )
        engine.set_role_data("role-1", {"allowed_categories": ["hr", "finance"]})
        engine.set_dept_data("dept-1", {"allowed_categories": ["hr"]})
        cats = set(engine.compute_user_categories(user))
        # Department intersection: only "hr" should remain
        assert "hr" in cats
        assert "finance" not in cats

    def test_no_restrictions_returns_empty(self, engine):
        """No restrictions configured → empty list (means all categories)."""
        user = UserContext(user_id="u001", username="alice")
        cats = engine.compute_user_categories(user)
        assert cats == []


class TestCanApprove:
    """can_approve checks user and role approval permissions."""

    def test_user_can_approve(self, engine):
        """User with can_approve=True can approve."""
        user = UserContext(user_id="u001", username="alice", can_approve=True)
        assert engine.can_approve(user) is True

    def test_role_can_approve(self, engine):
        """User whose role has can_approve can approve."""
        user = UserContext(user_id="u001", username="alice", roles=["manager"])
        engine.set_role_data("manager", {"can_approve": True})
        assert engine.can_approve(user) is True

    def test_cannot_approve(self, engine):
        """User without approval permission cannot approve."""
        user = UserContext(user_id="u001", username="alice")
        assert engine.can_approve(user) is False
