from typing import Optional
from pydantic import BaseModel, Field
class ChatRequest(BaseModel):
    message: str=Field(min_length=1,max_length=3000)
    customer_id: str="CUST-1001"
    case_id: Optional[str]=None
