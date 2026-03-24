from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "inter-agent-chat-codex"


class SkillPackageTests(unittest.TestCase):
    def test_skill_files_exist(self) -> None:
        self.assertTrue((SKILL_DIR / "SKILL.md").exists())
        self.assertTrue((SKILL_DIR / "agents" / "openai.yaml").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "register-codex-tty.py").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "list-codex-agents.py").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "capability-report.py").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "send-codex-message.py").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "unregister-codex-agent.py").exists())

    def test_skill_frontmatter_contains_name_description_and_hook(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        self.assertIn("name: inter-agent-chat-codex", content)
        self.assertIn("description:", content)
        self.assertIn("hooks:", content)
        self.assertIn("SessionStart:", content)
        self.assertIn("register-codex-tty.py", content)

    def test_openai_yaml_contains_default_prompt(self) -> None:
        content = (SKILL_DIR / "agents" / "openai.yaml").read_text()
        self.assertIn('display_name: "Inter-Agent Chat Codex"', content)
        self.assertIn("default_prompt:", content)
        self.assertIn("$inter-agent-chat-codex", content)

    def test_project_tools_and_pyproject_entrypoint_exist(self) -> None:
        project_toml = (ROOT / "pyproject.toml").read_text()
        self.assertIn("[project.scripts]", project_toml)
        self.assertIn('codex-inter-agent-chat = "codex_inter_agent_chat.cli:main"', project_toml)
        self.assertIn('codex-team = "codex_inter_agent_chat.team_cli:main"', project_toml)
        self.assertTrue((ROOT / "tools" / "install-skill.sh").exists())
        self.assertTrue((ROOT / "tools" / "uninstall-skill.sh").exists())
        self.assertTrue((ROOT / "tools" / "demo-two-agents.sh").exists())
        self.assertTrue((ROOT / "tools" / "codex-team.sh").exists())


if __name__ == "__main__":
    unittest.main()
