from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import validates

from .base import Base


class OPIConfiguration(Base):
    __tablename__ = "opi_configurations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opi_id = Column(String(50), unique=True, nullable=False, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    version = Column(String(20), nullable=False)
    description = Column(Text)
    configuration = Column(JSON)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __init__(self, **kwargs):
        if "opi_id" not in kwargs:
            raise TypeError("opi_id is required")
        if "version" not in kwargs:
            raise TypeError("version is required")
        super().__init__(**kwargs)

    def __str__(self):
        return f"OPIConfiguration(id={self.id}, opi_id='{self.opi_id}', version='{self.version}')"

    def __repr__(self):
        return self.__str__()

    def to_dict(self):
        """Convert model to dictionary"""
        return {
            "id": self.id,
            "opi_id": self.opi_id,
            "is_enabled": self.is_enabled,
            "version": self.version,
            "description": self.description,
            "configuration": self.configuration,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @validates("opi_id")
    def validate_opi_id(self, key, value):
        if not value or len(value) > 50:
            raise ValueError("opi_id must be between 1 and 50 characters")
        return value

    @validates("version")
    def validate_version(self, key, value):
        if not value or len(value) > 20:
            raise ValueError("version must be between 1 and 20 characters")
        return value