import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_name = Column(String)
    phone_number = Column(String, unique=True, nullable=False)
    parent_phone = Column(String)
    payments = relationship("Payment", back_populates="student")

    def __repr__(self):
        return f"<Student(name='{self.name}', phone='{self.phone_number}', parent_phone='{self.parent_phone}')>"

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    amount = Column(Float)
    transaction_id = Column(String, unique=True)
    date_received = Column(DateTime, default=datetime.datetime.utcnow)
    screenshot_path = Column(String)
    ocr_text = Column(Text)
    sender_phone = Column(String)
    additional_notes = Column(Text)
    status = Column(String, default="Pending") # Pending, Verified, Rejected
    
    student = relationship("Student", back_populates="payments")

    def __repr__(self):
        return f"<Payment(amount={self.amount}, status='{self.status}')>"

class AllowedGroup(Base):
    __tablename__ = 'allowed_groups'
    id = Column(Integer, primary_key=True)
    group_jid = Column(String, unique=True, nullable=False)
    group_name = Column(String)

    def __repr__(self):
        return f"<AllowedGroup(name='{self.group_name}', jid='{self.group_jid}')>"

# Database setup
ENGINE = create_engine('sqlite:///feetrack.db')
Base.metadata.create_all(ENGINE)
Session = sessionmaker(bind=ENGINE)

def get_session():
    return Session()

if __name__ == "__main__":
    print("Database and tables created successfully.")
