"""
File operation tools.
"""

from pathlib import Path
from typing import Optional


class FileTools:
    """Tools for file operations."""

    @staticmethod
    def read_file(file_path: str) -> Optional[str]:
        """
        Read file contents.

        Args:
            file_path: Path to file

        Returns:
            File contents or None if error
        """
        try:
            path = Path(file_path)
            if not path.exists():
                print(f"❌ File not found: {file_path}")
                return None

            with open(path, 'r', encoding='utf-8') as f:
                return f.read()

        except Exception as e:
            print(f"❌ Error reading file {file_path}: {e}")
            return None

    @staticmethod
    def write_file(file_path: str, content: str) -> bool:
        """
        Write content to file.

        Args:
            file_path: Path to file
            content: Content to write

        Returns:
            True if successful, False otherwise
        """
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)

            return True

        except Exception as e:
            print(f"❌ Error writing file {file_path}: {e}")
            return False

    @staticmethod
    def edit_file(file_path: str, old_text: str, new_text: str) -> bool:
        """
        Edit file by replacing text.

        Args:
            file_path: Path to file
            old_text: Text to replace
            new_text: Replacement text

        Returns:
            True if successful, False otherwise
        """
        try:
            content = FileTools.read_file(file_path)
            if content is None:
                return False

            if old_text not in content:
                print(f"⚠️  Text not found in {file_path}")
                return False

            new_content = content.replace(old_text, new_text)
            return FileTools.write_file(file_path, new_content)

        except Exception as e:
            print(f"❌ Error editing file {file_path}: {e}")
            return False

    @staticmethod
    def append_to_file(file_path: str, content: str) -> bool:
        """
        Append content to file.

        Args:
            file_path: Path to file
            content: Content to append

        Returns:
            True if successful, False otherwise
        """
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)

            return True

        except Exception as e:
            print(f"❌ Error appending to file {file_path}: {e}")
            return False

    @staticmethod
    def file_exists(file_path: str) -> bool:
        """
        Check if file exists.

        Args:
            file_path: Path to file

        Returns:
            True if exists, False otherwise
        """
        return Path(file_path).exists()

    @staticmethod
    def list_files(directory: str, pattern: str = "*") -> list[str]:
        """
        List files in directory matching pattern.

        Args:
            directory: Directory path
            pattern: Glob pattern (default: all files)

        Returns:
            List of file paths
        """
        try:
            path = Path(directory)
            if not path.exists():
                return []

            return [str(f) for f in path.glob(pattern) if f.is_file()]

        except Exception as e:
            print(f"❌ Error listing files in {directory}: {e}")
            return []
