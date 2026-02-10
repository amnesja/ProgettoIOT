from pydantic import BaseModel, Field

class RoomCreate(BaseModel):
    id: str = Field(..., example="living")
    name: str = Field(..., example="Soggiorno")
    target_temp: float = Field(21.0, example=21.5)
    hysteresis: float = Field(0.5, example=0.5)

class ValveRegister(BaseModel):
    id: str = Field(..., example="valve1")
    room_id: str | None = Field(None, example="living")
    meta: dict | None = Field(None, example={})


class SetpointModel(BaseModel):
    setpoint: float