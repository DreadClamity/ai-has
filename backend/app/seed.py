from sqlalchemy import text

from app.core.security import hash_password
from app.database import SessionLocal

DEMO_USERS = [
    {
        "email": "admin@aihas.local",
        "full_name": "Alex Admin",
        "password": "Admin123!",
        "role": "admin",
        "department": "IT Operations",
    },
    {
        "email": "agent@aihas.local",
        "full_name": "Ana Agent",
        "password": "Agent123!",
        "role": "agent",
        "department": "IT Service Desk",
    },
    {
        "email": "employee@aihas.local",
        "full_name": "Eli Employee",
        "password": "Employee123!",
        "role": "employee",
        "department": "Finance",
    },
]


def run() -> None:
    db = SessionLocal()
    try:
        for user in DEMO_USERS:
            result = db.execute(
                text(
                    """
                    INSERT INTO users (email, full_name, password_hash, role, department)
                    VALUES (:email, :full_name, :password_hash,
                            CAST(:role AS user_role), :department)
                    ON CONFLICT (email) DO NOTHING
                    """
                ),
                {
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "password_hash": hash_password(user["password"]),
                    "role": user["role"],
                    "department": user["department"],
                },
            )
            status = "created" if result.rowcount else "already exists"
            print(f"{user['email']:<24} ({user['role']:<8}) -> {status}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run()