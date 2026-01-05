"""Category data model."""

from typing import Optional
from pydantic import BaseModel, Field


class Category(BaseModel):
    """Represents a row in the Categories tab.

    Attributes:
        category: Hierarchical account name (e.g., "Expenses:Groceries")
        active: Whether category appears in dropdown
        notes: Optional notes for user reference
        sheet_row_index: Sheet row number for updates (not stored in sheet)
    """

    category: str
    active: bool = True
    notes: Optional[str] = None

    # Sheet metadata (not stored in sheet)
    sheet_row_index: Optional[int] = Field(default=None, exclude=True)
