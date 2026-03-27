from sqlalchemy import Column, String, Float, Integer, Text, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from app.utils.database_conn import Base

class Restaurant(Base):
    __tablename__ = "all_places"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    address = Column(String(255))
    lat = Column(Float)
    lng = Column(Float)
    phone = Column(String(50))
    website = Column(Text)
    map_url = Column(String(512))
    opening_hours = Column(Text)
    rating = Column(Float)
    attributes = relationship("PlaceAttribute", back_populates="restaurant", uselist=False)

class PlaceAttribute(Base):
    __tablename__ = "Place_Attributes"
    place_id = Column(Integer, ForeignKey("all_places.id"), primary_key=True)
    food_type = Column(String(255))
    cuisine_type = Column(String(255))
    merchant_category = Column(String(255))
    facility_tags = Column(JSON)
    restaurant = relationship("Restaurant", back_populates="attributes")