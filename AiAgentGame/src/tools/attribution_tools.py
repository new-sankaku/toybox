"""
Attribution tools for managing asset licenses and credits.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from ..core.state import Attribution
from ..utils.logger import get_logger

logger = get_logger()


class AttributionManager:
    """Manages attribution information for all assets."""

    def __init__(self, output_file: str = "output/attribution.json"):
        """Initialize attribution manager."""
        self.output_file = Path(output_file)
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.attributions: List[Attribution] = []

        # Load existing attributions
        self._load()

    def add_attribution(
        self,
        asset_id: str,
        asset_type: str,
        source_type: str,
        source_url: str = "",
        source_name: str = "",
        author: str = "",
        license: str = "",
        license_url: str = "",
        requires_credit: bool = False,
        credit_text: str = "",
        notes: str = ""
    ) -> None:
        """
        Add attribution for an asset.

        Args:
            asset_id: Unique asset identifier
            asset_type: Type of asset (image, audio, font, icon)
            source_type: Source type (free_asset, generated, purchased)
            source_url: URL where asset was obtained
            source_name: Name of source site
            author: Asset creator/author
            license: License type (CC0, CC-BY, etc.)
            license_url: URL to license text
            requires_credit: Whether credit is required
            credit_text: Credit text if required
            notes: Additional notes
        """
        attribution = Attribution(
            asset_id=asset_id,
            asset_type=asset_type,
            source_type=source_type,
            source_url=source_url,
            source_name=source_name,
            author=author,
            license=license,
            license_url=license_url,
            requires_credit=requires_credit,
            credit_text=credit_text,
            downloaded_at=datetime.now().isoformat(),
            notes=notes
        )

        self.attributions.append(attribution)
        self._save()

    def add_mock_attribution(self, asset_id: str, asset_type: str) -> None:
        """
        Add attribution for a mock/generated asset.

        Args:
            asset_id: Asset identifier
            asset_type: Asset type
        """
        self.add_attribution(
            asset_id=asset_id,
            asset_type=asset_type,
            source_type="generated",
            source_name="AI Agent Game Creator",
            author="System Generated",
            license="CC0",
            requires_credit=False,
            notes="Mock asset for rapid prototyping"
        )

    def get_credits_text(self) -> str:
        """
        Generate credits text for all assets requiring credit.

        Returns:
            Formatted credits text
        """
        credits = []
        credits.append("# Credits and Attributions\n")

        # Group by license type
        by_license: Dict[str, List[Attribution]] = {}
        for attr in self.attributions:
            if attr.get("requires_credit", False):
                license = attr.get("license", "Unknown")
                if license not in by_license:
                    by_license[license] = []
                by_license[license].append(attr)

        for license, attrs in by_license.items():
            credits.append(f"\n## {license}\n")
            for attr in attrs:
                credits.append(f"- {attr.get('credit_text', '')}")
                if attr.get("source_url"):
                    credits.append(f"  Source: {attr.get('source_url')}")

        # Add sources that don't require credit but should be acknowledged
        credits.append("\n## Additional Sources\n")
        for attr in self.attributions:
            if not attr.get("requires_credit", False) and attr.get("source_type") == "free_asset":
                credits.append(f"- {attr.get('asset_id')}: {attr.get('source_name', 'Unknown')}")

        return "\n".join(credits)

    def generate_credits_file(self, output_path: str = "output/CREDITS.md") -> None:
        """
        Generate a CREDITS.md file.

        Args:
            output_path: Path for credits file
        """
        credits_text = self.get_credits_text()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(credits_text)

        logger.info(f"クレジットファイル生成: {output_path}")

    def _load(self) -> None:
        """Load existing attributions from file."""
        if self.output_file.exists():
            try:
                with open(self.output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.attributions = data.get("attributions", [])
            except Exception as e:
                logger.warning(f"アトリビューション読込エラー: {e}")
                self.attributions = []

    def _save(self) -> None:
        """Save attributions to file."""
        try:
            data = {
                "attributions": self.attributions,
                "generated_at": datetime.now().isoformat(),
                "total_assets": len(self.attributions)
            }

            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"アトリビューション保存エラー: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of attributions.

        Returns:
            Dictionary with statistics
        """
        by_type = {}
        by_license = {}
        requires_credit = 0

        for attr in self.attributions:
            asset_type = attr.get("asset_type", "unknown")
            license = attr.get("license", "unknown")

            by_type[asset_type] = by_type.get(asset_type, 0) + 1
            by_license[license] = by_license.get(license, 0) + 1

            if attr.get("requires_credit", False):
                requires_credit += 1

        return {
            "total_assets": len(self.attributions),
            "by_type": by_type,
            "by_license": by_license,
            "requires_credit": requires_credit
        }

    def print_summary(self) -> None:
        """Print attribution summary."""
        summary = self.get_summary()

        logger.info("アトリビューション概要:")
        logger.info(f"  総アセット数: {summary['total_assets']}")
        logger.info(f"  クレジット必要: {summary['requires_credit']}")

        logger.info("  タイプ別:")
        for asset_type, count in summary['by_type'].items():
            logger.info(f"    - {asset_type}: {count}")

        logger.info("  ライセンス別:")
        for license, count in summary['by_license'].items():
            logger.info(f"    - {license}: {count}")
