"""Edit matching strategies for flexible string replacement.

This module provides multiple strategies for finding and replacing text in files,
allowing for some flexibility when the model's output doesn't perfectly match
the file content (e.g., whitespace differences, indentation issues).

Strategies are tried in order from most precise to least precise.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class MatchResult:
    """Result of a match attempt."""

    success: bool
    start_pos: int = -1
    end_pos: int = -1
    matched_text: str = ""
    strategy_name: str = ""


class EditStrategy(ABC):
    """Base class for edit matching strategies."""

    name: str = "base"

    @abstractmethod
    def find_match(self, content: str, search: str) -> MatchResult:
        """Find a match for the search string in content.

        Args:
            content: The file content to search in
            search: The string to find

        Returns:
            MatchResult indicating success and position
        """
        pass


class ExactMatchStrategy(EditStrategy):
    """Exact string matching (default behavior)."""

    name = "exact"

    def find_match(self, content: str, search: str) -> MatchResult:
        count = content.count(search)
        if count == 1:
            pos = content.find(search)
            return MatchResult(
                success=True,
                start_pos=pos,
                end_pos=pos + len(search),
                matched_text=search,
                strategy_name=self.name,
            )
        return MatchResult(success=False, strategy_name=self.name)


class LineTrimmedStrategy(EditStrategy):
    """Match after trimming trailing whitespace from each line.

    Useful when the model adds or removes trailing spaces.
    """

    name = "line_trimmed"

    def find_match(self, content: str, search: str) -> MatchResult:
        def trim_lines(text: str) -> str:
            return "\n".join(line.rstrip() for line in text.split("\n"))

        trimmed_content = trim_lines(content)
        trimmed_search = trim_lines(search)

        count = trimmed_content.count(trimmed_search)
        if count == 1:
            # Find position in trimmed content
            trimmed_pos = trimmed_content.find(trimmed_search)

            # Map back to original content position
            # Count newlines before the match to find the starting line
            lines_before = trimmed_content[:trimmed_pos].count("\n")
            original_lines = content.split("\n")

            # Calculate position in original
            if lines_before == 0:
                original_pos = 0
            else:
                original_pos = sum(len(line) + 1 for line in original_lines[:lines_before])

            # Add offset within the line
            trimmed_lines_before = trimmed_content[:trimmed_pos].split("\n")
            offset_in_line = len(trimmed_lines_before[-1]) if trimmed_lines_before else 0
            original_pos += offset_in_line

            # Calculate the end position by finding where the match ends
            search_line_count = trimmed_search.count("\n")
            end_line = lines_before + search_line_count

            # Get the matched text from original
            matched_lines = original_lines[lines_before:end_line + 1]
            matched_text = "\n".join(matched_lines)

            return MatchResult(
                success=True,
                start_pos=original_pos,
                end_pos=original_pos + len(matched_text),
                matched_text=matched_text,
                strategy_name=self.name,
            )

        return MatchResult(success=False, strategy_name=self.name)


class BlockAnchorStrategy(EditStrategy):
    """Match by finding unique anchor lines at start and end of block.

    Useful when the middle content matches but there are minor differences.
    """

    name = "block_anchor"

    def find_match(self, content: str, search: str) -> MatchResult:
        search_lines = search.split("\n")
        if len(search_lines) < 2:
            return MatchResult(success=False, strategy_name=self.name)

        content_lines = content.split("\n")

        # Use first and last non-empty lines as anchors
        first_anchor = ""
        for line in search_lines:
            if line.strip():
                first_anchor = line.strip()
                break

        last_anchor = ""
        for line in reversed(search_lines):
            if line.strip():
                last_anchor = line.strip()
                break

        if not first_anchor or not last_anchor:
            return MatchResult(success=False, strategy_name=self.name)

        # Find first anchor
        first_matches = [
            i for i, line in enumerate(content_lines)
            if line.strip() == first_anchor
        ]

        if len(first_matches) != 1:
            return MatchResult(success=False, strategy_name=self.name)

        start_line = first_matches[0]

        # Find last anchor after start
        expected_lines = len(search_lines)

        for end_line in range(start_line + 1, min(start_line + expected_lines + 5, len(content_lines))):
            if content_lines[end_line].strip() == last_anchor:
                actual_lines = end_line - start_line + 1
                # Allow some flexibility (within 2 lines)
                if abs(actual_lines - expected_lines) <= 2:
                    # Calculate positions
                    start_pos = sum(len(line) + 1 for line in content_lines[:start_line])
                    end_pos = sum(len(line) + 1 for line in content_lines[:end_line + 1])
                    matched_text = "\n".join(content_lines[start_line:end_line + 1])

                    return MatchResult(
                        success=True,
                        start_pos=start_pos,
                        end_pos=end_pos,
                        matched_text=matched_text,
                        strategy_name=self.name,
                    )

        return MatchResult(success=False, strategy_name=self.name)


class IndentationFlexibleStrategy(EditStrategy):
    """Match content while allowing different indentation levels.

    Useful when the model uses a different number of spaces for indentation.
    """

    name = "indentation_flexible"

    def find_match(self, content: str, search: str) -> MatchResult:
        def strip_common_indent(text: str) -> Tuple[str, int]:
            """Strip common leading indent and return normalized text and indent level."""
            lines = text.split("\n")
            non_empty_lines = [line for line in lines if line.strip()]
            if not non_empty_lines:
                return text, 0

            # Find minimum indent
            min_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines)

            # Strip that indent from all lines
            stripped_lines = []
            for line in lines:
                if line.strip():
                    stripped_lines.append(line[min_indent:])
                else:
                    stripped_lines.append("")

            return "\n".join(stripped_lines), min_indent

        search_normalized, _ = strip_common_indent(search)

        # Try to find the search pattern with any indentation
        content_lines = content.split("\n")

        # Find potential starting points
        search_first_line = search_normalized.split("\n")[0].strip()
        if not search_first_line:
            return MatchResult(success=False, strategy_name=self.name)

        for i, line in enumerate(content_lines):
            if line.strip() == search_first_line:
                # Found potential start, check if rest matches
                search_lines = search_normalized.split("\n")
                match_lines = content_lines[i:i + len(search_lines)]

                if len(match_lines) < len(search_lines):
                    continue

                # Compare stripped versions
                matches = True
                for s_line, c_line in zip(search_lines, match_lines):
                    if s_line.strip() != c_line.strip():
                        matches = False
                        break

                if matches:
                    # Check uniqueness - are there other matches?
                    other_matches = 0
                    for j, other_line in enumerate(content_lines):
                        if j != i and other_line.strip() == search_first_line:
                            # Check if this is also a full match
                            other_match_lines = content_lines[j:j + len(search_lines)]
                            if len(other_match_lines) == len(search_lines):
                                other_matches_all = True
                                for s_line, o_line in zip(search_lines, other_match_lines):
                                    if s_line.strip() != o_line.strip():
                                        other_matches_all = False
                                        break
                                if other_matches_all:
                                    other_matches += 1

                    if other_matches == 0:
                        # Unique match found
                        start_pos = sum(len(line) + 1 for line in content_lines[:i])
                        matched_text = "\n".join(match_lines)
                        end_pos = start_pos + len(matched_text)

                        return MatchResult(
                            success=True,
                            start_pos=start_pos,
                            end_pos=end_pos,
                            matched_text=matched_text,
                            strategy_name=self.name,
                        )

        return MatchResult(success=False, strategy_name=self.name)


class EscapeNormalizedStrategy(EditStrategy):
    """Match after normalizing escape sequences.

    Useful when the model outputs literal \\n instead of actual newlines.
    """

    name = "escape_normalized"

    def find_match(self, content: str, search: str) -> MatchResult:
        def normalize_escapes(text: str) -> str:
            """Normalize common escape sequences."""
            result = text
            result = result.replace("\\n", "\n")
            result = result.replace("\\t", "\t")
            result = result.replace("\\r", "\r")
            result = result.replace('\\"', '"')
            result = result.replace("\\'", "'")
            result = result.replace("\\\\", "\\")
            return result

        # Normalize the search string
        normalized_search = normalize_escapes(search)

        # Only proceed if normalization actually changed something
        if normalized_search == search:
            return MatchResult(success=False, strategy_name=self.name)

        count = content.count(normalized_search)
        if count == 1:
            pos = content.find(normalized_search)
            return MatchResult(
                success=True,
                start_pos=pos,
                end_pos=pos + len(normalized_search),
                matched_text=normalized_search,
                strategy_name=self.name,
            )

        return MatchResult(success=False, strategy_name=self.name)


class WhitespaceNormalizedStrategy(EditStrategy):
    """Match after normalizing all whitespace to single spaces.

    This is a last resort strategy - least precise but most flexible.
    """

    name = "whitespace_normalized"

    def find_match(self, content: str, search: str) -> MatchResult:
        def normalize(text: str) -> str:
            return " ".join(text.split())

        norm_content = normalize(content)
        norm_search = normalize(search)

        if not norm_search:
            return MatchResult(success=False, strategy_name=self.name)

        count = norm_content.count(norm_search)
        if count == 1:
            # Find in normalized content
            norm_pos = norm_content.find(norm_search)

            # Try to map back to original content - this is approximate
            # Find the word that starts our match
            words_before = norm_content[:norm_pos].count(" ")

            # Walk through original content counting words
            original_pos = 0
            word_count = 0
            in_whitespace = True

            for i, char in enumerate(content):
                if char.isspace():
                    in_whitespace = True
                else:
                    if in_whitespace:
                        word_count += 1
                        in_whitespace = False
                    if word_count > words_before:
                        original_pos = i
                        break

            # This strategy has imprecise positioning
            # Return success but note that positions are approximate
            return MatchResult(
                success=True,
                start_pos=original_pos,
                end_pos=-1,  # End position not reliable
                matched_text="",  # Matched text not reliable
                strategy_name=self.name,
            )

        return MatchResult(success=False, strategy_name=self.name)


# Ordered list of strategies to try (most precise to least precise)
DEFAULT_STRATEGIES: List[EditStrategy] = [
    ExactMatchStrategy(),
    LineTrimmedStrategy(),
    BlockAnchorStrategy(),
    IndentationFlexibleStrategy(),
    EscapeNormalizedStrategy(),
    WhitespaceNormalizedStrategy(),  # Last resort
]


def find_best_match(
    content: str,
    search: str,
    strategies: Optional[List[EditStrategy]] = None,
) -> MatchResult:
    """Try multiple strategies to find a match.

    Args:
        content: The file content
        search: The string to find
        strategies: Strategies to try (default: DEFAULT_STRATEGIES)

    Returns:
        MatchResult from the first successful strategy
    """
    if strategies is None:
        strategies = DEFAULT_STRATEGIES

    for strategy in strategies:
        result = strategy.find_match(content, search)
        if result.success:
            return result

    return MatchResult(success=False, strategy_name="none")


def apply_edit(
    content: str,
    old_string: str,
    new_string: str,
) -> Tuple[bool, str, str]:
    """Apply an edit using fallback strategies.

    Args:
        content: Original file content
        old_string: String to replace
        new_string: Replacement string

    Returns:
        Tuple of (success, new_content, strategy_used)
    """
    # Fast path: try exact match first
    count = content.count(old_string)
    if count == 1:
        return True, content.replace(old_string, new_string, 1), "exact"

    if count > 1:
        return False, content, f"exact_multiple_{count}"

    # Exact match failed (count == 0), try fallback strategies
    result = find_best_match(content, old_string)

    if not result.success:
        return False, content, "no_match"

    # Apply the edit based on the match result
    if result.matched_text and result.start_pos >= 0:
        # We have the matched text, replace it
        new_content = (
            content[:result.start_pos] +
            new_string +
            content[result.start_pos + len(result.matched_text):]
        )
        return True, new_content, result.strategy_name

    if result.start_pos >= 0 and result.end_pos >= 0:
        # We have positions, use them directly
        new_content = (
            content[:result.start_pos] +
            new_string +
            content[result.end_pos:]
        )
        return True, new_content, result.strategy_name

    # Strategy matched but couldn't provide precise replacement info
    # This shouldn't happen with well-implemented strategies
    return False, content, f"{result.strategy_name}_imprecise"
