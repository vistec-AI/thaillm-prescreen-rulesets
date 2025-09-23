from typing import List
from pydantic import BaseModel


class SeverityLevel(BaseModel):
    name: str
    name_th: str
    description: str


class Disease(BaseModel):
    id: str
    original_value: str
    disease_name: str
    name_th: str
    description: str
    available_severity: List[str]

class NHSOSymptoms(BaseModel):
    name: str
    name_th: str


class Department(BaseModel):
    id: str
    name: str
    name_th: str
    description: str