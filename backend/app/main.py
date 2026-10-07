from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from typing import Literal
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload
import jwt
from app.core.config import settings
from app.core.database import Base, engine, get_db
from app.core.security import create_token, hash_password, verify_password
from app.modules.models import Department, Notification, Request, RequestApproval, RequestHistory, RequestType, Role, User, Workflow, WorkflowStep

bearer = HTTPBearer()
DEPARTMENT_NAMES = ("Marketing", "Engineering", "المالية", "التنسيق", "Automation", "الانتاج", "فني مصنع", "Drawing")
MANAGER_DEPARTMENT_NAMES = tuple(name for name in DEPARTMENT_NAMES if name not in {"فني مصنع", "Drawing"})
STATUS = {"DRAFT": "مسودة", "PENDING_EXECUTIVE": "بانتظار موافقة المدير التنفيذي", "REJECTED_EXECUTIVE": "مرفوض من المدير التنفيذي", "PENDING_DEPARTMENT_MANAGER": "بانتظار موافقة مسؤول القسم", "REJECTED_DEPARTMENT_MANAGER": "مرفوض من مسؤول القسم", "PENDING_DRAWING": "بانتظار موافقة قسم Drawing", "REJECTED_DRAWING": "مرفوض من قسم Drawing", "PENDING_HR": "بانتظار موافقة الموارد البشرية", "REJECTED_HR": "مرفوض من الموارد البشرية", "APPROVED": "موافق عليه"}


def pending_status(role_code: str) -> str:
    return {"EXECUTIVE_MANAGER": "PENDING_EXECUTIVE", "DRAWING": "PENDING_DRAWING", "HR": "PENDING_HR"}.get(role_code, f"PENDING_{role_code}")


def rejected_status(role_code: str) -> str:
    return {"EXECUTIVE_MANAGER": "REJECTED_EXECUTIVE", "DRAWING": "REJECTED_DRAWING", "HR": "REJECTED_HR"}.get(role_code, f"REJECTED_{role_code}")


def status_label(code: str) -> str:
    return STATUS.get(code, code.replace("PENDING_", "بانتظار موافقة ").replace("REJECTED_", "مرفوض من "))


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class SignupInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    department_id: int
    role_code: Literal["EMPLOYEE", "DEPARTMENT_MANAGER"] = "EMPLOYEE"


class RequestInput(BaseModel):
    request_type_code: str
    form_data: dict


class DecisionInput(BaseModel):
    action: str
    comment: str | None = Field(default=None, max_length=2000)


class UserCreateInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    employee_id: str = Field(min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(min_length=12)
    role_code: str
    department_id: int | None = None


class UserUpdateInput(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=12)
    role_code: str | None = None
    department_id: int | None = None
    active: bool | None = None


class RegistrationDecisionInput(BaseModel):
    action: Literal["APPROVE", "REJECT"]


class DepartmentInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class RequestTypeInput(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name_ar: str = Field(min_length=2, max_length=150)
    fields: list[dict] = Field(default_factory=list)
    workflow_roles: list[str] = Field(default_factory=lambda: ["EXECUTIVE_MANAGER", "HR"])
    active: bool = True


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="جلسة غير صالحة")
    return user


def require_roles(*roles: str):
    def guard(user: User = Depends(current_user)):
        if user.role.code not in roles:
            raise HTTPException(status_code=403, detail="ليس لديك صلاحية لهذا الإجراء")
        return user
    return guard


def serialize_request(r: Request) -> dict:
    current_role = r.approval_route[r.current_step - 1] if r.approval_route and r.current_step and r.current_step <= len(r.approval_route) else {"PENDING_EXECUTIVE": "EXECUTIVE_MANAGER", "PENDING_DEPARTMENT_MANAGER": "DEPARTMENT_MANAGER", "PENDING_DRAWING": "DRAWING", "PENDING_HR": "HR"}.get(r.status)
    return {"id": r.id, "request_type": {"code": r.request_type.code, "name_ar": r.request_type.name_ar}, "requester": {"id": r.requester.id, "full_name": r.requester.full_name, "employee_id": r.requester.employee_id}, "status": r.status, "status_label": status_label(r.status), "current_step": r.current_step, "current_role": current_role, "form_data": r.form_data, "created_at": r.created_at, "updated_at": r.updated_at,
            "approvals": [{"action": a.action, "comment": a.comment, "step": a.step_position, "reviewer": a.reviewer.full_name, "at": a.created_at} for a in r.approvals],
            "history": [{"action": h.action, "comment": h.comment, "role": h.actor_role, "actor": h.actor.full_name if h.actor else None, "at": h.created_at} for h in r.history]}


def log(db: Session, request: Request, actor: User, action: str, comment: str | None = None):
    db.add(RequestHistory(request_id=request.id, actor_id=actor.id, actor_role=actor.role.code, action=action, comment=comment))


def replace_notification(db: Session, recipient_id: int, request: Request, message: str):
    db.execute(delete(Notification).where(Notification.recipient_id == recipient_id))
    db.add(Notification(recipient_id=recipient_id, request_id=request.id, message=message))


def notify_role(db: Session, role_code: str, request: Request, message: str):
    users = db.scalars(select(User).join(Role).where(Role.code == role_code, User.active.is_(True))).all()
    for user in users:
        replace_notification(db, user.id, request, message)


def has_department_manager(db: Session, department_id: int | None) -> bool:
    if department_id is None:
        return False
    return db.scalar(select(User.id).join(Role).where(Role.code == "DEPARTMENT_MANAGER", User.department_id == department_id, User.active.is_(True)).limit(1)) is not None


def has_drawing_employee(db: Session) -> bool:
    return db.scalar(select(User.id).join(Department, User.department_id == Department.id).join(Role).where(Department.name == "Drawing", Role.code == "EMPLOYEE", User.active.is_(True)).limit(1)) is not None


def manager_department_id_for_request(db: Session, request: Request) -> int | None:
    if request.requester.department and request.requester.department.name == "Drawing":
        return db.scalar(select(Department.id).where(Department.name == "الانتاج"))
    return request.requester.department_id


def is_department_manager_for_request(user: User, request: Request) -> bool:
    if user.department_id == request.requester.department_id:
        return True
    return bool(
        user.department
        and user.department.name == "الانتاج"
        and request.requester.department
        and request.requester.department.name == "Drawing"
    )


def department_manager_inbox_filter(user: User):
    departments = [Request.requester.has(User.department_id == user.department_id)]
    if user.department and user.department.name == "الانتاج":
        departments.append(Request.requester.has(User.department.has(Department.name == "Drawing")))
    return and_(Request.status == pending_status(user.role.code), or_(*departments))


def notify_approver(db: Session, role_code: str, request: Request, message: str):
    if role_code == "DEPARTMENT_MANAGER":
        department_id = manager_department_id_for_request(db, request)
        users = db.scalars(select(User).join(Role).where(Role.code == role_code, User.department_id == department_id, User.active.is_(True))).all()
        for user in users:
            replace_notification(db, user.id, request, message)
    elif role_code == "DRAWING":
        users = db.scalars(select(User).join(Department, User.department_id == Department.id).join(Role).where(Department.name == "Drawing", Role.code == "EMPLOYEE", User.active.is_(True))).all()
        for user in users:
            replace_notification(db, user.id, request, message)
    else:
        notify_role(db, role_code, request, message)


def approval_steps(request: Request, workflow: Workflow | None) -> list[tuple[int, str]]:
    if request.approval_route is not None:
        return list(enumerate(request.approval_route, 1))
    return [(step.position, step.role_code) for step in workflow.steps] if workflow else []


def approval_route(db: Session, request_type: RequestType, user: User, workflow: Workflow) -> list[str]:
    if user.email.strip().lower() == "mohamadr2002@gmail.com":
        route = ["EXECUTIVE_MANAGER", "HR"]
    elif user.role.code == "HR":
        route = ["EXECUTIVE_MANAGER"]
    elif user.role.code == "DEPARTMENT_MANAGER":
        route = ["EXECUTIVE_MANAGER", "HR"]
    elif user.role.code == "EMPLOYEE" and user.department and user.department.name == "Drawing":
        production_department_id = db.scalar(select(Department.id).where(Department.name == "الانتاج"))
        if not has_department_manager(db, production_department_id):
            raise HTTPException(422, "لا يوجد مسؤول قسم نشط لقسم الانتاج لاستقبال طلبات Drawing")
        route = ["DEPARTMENT_MANAGER", "HR"]
    elif request_type.code == "VEHICLE_MILEAGE":
        route = ["EXECUTIVE_MANAGER", "HR"]
    elif request_type.code in {"LEAVE", "OVERTIME"} and user.role.code == "EMPLOYEE":
        if user.department and user.department.name == "فني مصنع":
            route = ["DRAWING", "HR"] if has_drawing_employee(db) else ["HR"]
        else:
            route = ["DEPARTMENT_MANAGER", "HR"] if has_department_manager(db, user.department_id) else ["HR"]
    else:
        route = [step.role_code for step in workflow.steps]
    manager_department_id = (
        db.scalar(select(Department.id).where(Department.name == "الانتاج"))
        if user.role.code == "EMPLOYEE" and user.department and user.department.name == "Drawing"
        else user.department_id
    )
    if "DEPARTMENT_MANAGER" in route and not has_department_manager(db, manager_department_id):
        route = [role_code for role_code in route if role_code != "DEPARTMENT_MANAGER"]
    return route


def validate_department_assignment(db: Session, role_code: str, department_id: int | None):
    if role_code in {"EMPLOYEE", "DEPARTMENT_MANAGER"} and department_id is None:
        raise HTTPException(422, "القسم مطلوب لهذا الدور")
    if department_id is None:
        return
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(422, "القسم غير موجود")
    if role_code == "EMPLOYEE" and department.name not in DEPARTMENT_NAMES:
        raise HTTPException(422, "اختر قسمًا من الأقسام المعتمدة")
    if role_code == "DEPARTMENT_MANAGER" and department.name not in MANAGER_DEPARTMENT_NAMES:
        raise HTTPException(422, "لا يمكن تعيين مسؤول لقسم فني مصنع أو Drawing")


def ensure_request_catalog(db: Session):
    role_names = {
        "EMPLOYEE": "موظف",
        "EXECUTIVE_MANAGER": "المدير التنفيذي",
        "DEPARTMENT_MANAGER": "مسؤول القسم",
        "HR": "الموارد البشرية",
    }
    roles = {}
    for code, name in role_names.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name_ar=name)
            db.add(role)
            db.flush()
        roles[code] = role

    for name in DEPARTMENT_NAMES:
        if db.scalar(select(Department.id).where(Department.name == name)) is None:
            db.add(Department(name=name))

    definitions = [
        (
            "LEAVE",
            "طلب إجازة أو مغادرة",
            [
                {"key": "request_kind", "label": "نوع الطلب", "type": "select", "required": True, "options": ["مغادرة", "إجازة"]},
                {"key": "request_date", "label": "التاريخ", "type": "date", "required": True},
                {"key": "from_time", "label": "من وقت", "type": "time"},
                {"key": "to_time", "label": "إلى وقت", "type": "time"},
                {"key": "leave_details", "label": "تفاصيل الإجازة أو المغادرة", "type": "textarea"},
                {"key": "leave_period", "label": "مدة الإجازة", "type": "select", "options": ["يوم واحد", "عدة أيام"]},
                {"key": "from_date", "label": "من تاريخ", "type": "date"},
                {"key": "to_date", "label": "إلى تاريخ", "type": "date"},
                {"key": "last_leave_date", "label": "تاريخ آخر إجازة", "type": "date"},
            ],
        ),
        (
            "VEHICLE_MILEAGE",
            "عداد السيارات",
            [
                {"key": "date", "label": "التاريخ", "type": "date", "required": True},
                {"key": "vehicle", "label": "السيارة", "type": "text", "required": True},
                {"key": "project_name", "label": "اسم المشروع", "type": "text", "required": True},
                {"key": "meter_reading", "label": "رقم العداد", "type": "number", "required": True},
                {"key": "price_per_km", "label": "سعر الكيلو", "type": "number", "required": True},
                {"key": "value", "label": "القيمة", "type": "calculated", "formula": "meter_reading * price_per_km"},
            ],
        ),
        (
            "OVERTIME",
            "تقرير العمل الإضافي للقسم",
            [
                {"key": "report_date", "label": "التاريخ", "type": "date", "required": True},
                {"key": "employee_name", "label": "الاسم", "type": "text", "required": True},
                {"key": "project", "label": "المشروع", "type": "text", "required": True},
                {"key": "departure_time", "label": "وقت المغادرة", "type": "time", "required": True},
                {"key": "overtime_hours", "label": "عدد ساعات الإضافي", "type": "number", "required": True},
                {"key": "dinner_allowance", "label": "بدل عشاء", "type": "number"},
            ],
        ),
    ]
    for code, name, fields in definitions:
        request_type = db.scalar(select(RequestType).where(RequestType.code == code))
        if request_type is None:
            request_type = RequestType(code=code, name_ar=name, fields=fields)
            db.add(request_type)
            db.flush()
            workflow = Workflow(request_type_id=request_type.id, name=f"مسار {name}")
            db.add(workflow)
            db.flush()
            db.add_all([
                WorkflowStep(workflow_id=workflow.id, position=1, role_code="EXECUTIVE_MANAGER", label_ar="موافقة المدير التنفيذي"),
                WorkflowStep(workflow_id=workflow.id, position=2, role_code="HR", label_ar="موافقة الموارد البشرية"),
            ])
        elif code == "LEAVE" and isinstance(request_type.fields, list):
            request_type.fields = [
                field for field in request_type.fields
                if not isinstance(field, dict) or field.get("key") != "leave_balance"
            ]
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    with next(get_db()) as db:
        ensure_request_catalog(db)
    yield


app = FastAPI(title="TAFASEEL Digital Workflow API", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/", include_in_schema=False)
def home(): return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/auth/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).options(joinedload(User.role)).where(func.lower(User.email) == str(data.email).lower()))
    if not user or not user.active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": {"id":user.id,"name":user.full_name,"role":user.role.code,"role_name":user.role.name_ar,"department":user.department.name if user.department else None}}


@app.post("/api/auth/signup", status_code=201)
def signup(data: SignupInput, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="البريد الإلكتروني مسجل بالفعل")
    role = db.scalar(select(Role).where(Role.code == data.role_code))
    if not role:
        raise HTTPException(422, "الدور غير موجود")
    validate_department_assignment(db, data.role_code, data.department_id)
    user = User(
        full_name=data.full_name.strip(),
        employee_id=f"SELF-{uuid4().hex}",
        email=email,
        password_hash=hash_password(data.password),
        role_id=role.id,
        department_id=data.department_id,
        active=data.role_code != "DEPARTMENT_MANAGER",
        registration_status="PENDING" if data.role_code == "DEPARTMENT_MANAGER" else "APPROVED",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if data.role_code == "DEPARTMENT_MANAGER":
        return {"status": "PENDING_ACTIVATION", "message": "تم استلام طلب مسؤول القسم. يجب تفعيل الحساب من مسؤول النظام قبل تسجيل الدخول."}
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": {"id":user.id,"name":user.full_name,"role":role.code,"role_name":role.name_ar,"department":user.department.name if user.department else None}}


@app.get("/api/departments")
def departments(db: Session = Depends(get_db)):
    rows = db.scalars(select(Department).where(Department.name.in_(DEPARTMENT_NAMES))).all()
    by_name = {department.name: department for department in rows}
    return [{"id": by_name[name].id, "name": name} for name in DEPARTMENT_NAMES if name in by_name]


@app.get("/api/auth/me")
def auth_me(user: User = Depends(current_user)):
    return {"user": {"id":user.id,"name":user.full_name,"role":user.role.code,"role_name":user.role.name_ar,"department":user.department.name if user.department else None}}


@app.get("/api/request-types")
def request_types(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"code": r.code, "name_ar": r.name_ar, "fields": r.fields} for r in db.scalars(select(RequestType).where(RequestType.active.is_(True))).all()]


@app.post("/api/requests", status_code=201)
def create_request(data: RequestInput, user: User = Depends(require_roles("EMPLOYEE", "DEPARTMENT_MANAGER", "HR", "ADMIN")), db: Session = Depends(get_db)):
    rt = db.scalar(select(RequestType).where(RequestType.code == data.request_type_code, RequestType.active.is_(True)))
    if not rt: raise HTTPException(404, "نوع الطلب غير موجود")
    missing = [f["label"] for f in rt.fields if f.get("required") and not data.form_data.get(f["key"])]
    if missing: raise HTTPException(422, detail=f"حقول مطلوبة: {', '.join(missing)}")
    workflow = db.scalar(select(Workflow).options(joinedload(Workflow.steps)).where(Workflow.request_type_id == rt.id))
    if not workflow or not workflow.steps: raise HTTPException(422, "لا يوجد مسار موافقات معرف لهذا النوع")
    route = approval_route(db, rt, user, workflow)
    if not route: raise HTTPException(422, "لا يوجد مسار موافقات نشط لهذا النوع")
    first_role = route[0]
    req = Request(request_type_id=rt.id, requester_id=user.id, status=pending_status(first_role), current_step=1, form_data=data.form_data, approval_route=route)
    db.add(req); db.flush(); log(db, req, user, "REQUEST_SUBMITTED"); notify_approver(db, first_role, req, f"طلب جديد #{req.id} بانتظار موافقتك"); db.commit(); db.refresh(req)
    return {"id": req.id, "status": req.status}


@app.get("/api/requests")
def list_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Request).options(joinedload(Request.request_type), joinedload(Request.requester), joinedload(Request.approvals).joinedload(RequestApproval.reviewer), joinedload(Request.history).joinedload(RequestHistory.actor)).order_by(Request.updated_at.desc())
    if user.role.code == "EMPLOYEE":
        if user.department and user.department.name == "Drawing":
            factory_department_id = db.scalar(select(Department.id).where(Department.name == "فني مصنع"))
            if factory_department_id is not None:
                drawing_requests = and_(Request.status == "PENDING_DRAWING", Request.requester.has(User.department_id == factory_department_id))
                q = q.where(or_(Request.requester_id == user.id, drawing_requests))
            else:
                q = q.where(Request.requester_id == user.id)
        else:
            q = q.where(Request.requester_id == user.id)
    elif user.role.code == "DEPARTMENT_MANAGER":
        q = q.where(or_(Request.requester_id == user.id, department_manager_inbox_filter(user)))
    elif user.role.code == "HR":
        q = q.where(or_(Request.requester_id == user.id, Request.status == pending_status(user.role.code)))
    elif user.role.code != "ADMIN": q = q.where(Request.status == pending_status(user.role.code))
    return [serialize_request(r) for r in db.scalars(q).unique().all()]


@app.get("/api/hr/archive")
def hr_request_archive(user: User = Depends(require_roles("HR")), db: Session = Depends(get_db)):
    q = (
        select(Request)
        .options(
            joinedload(Request.request_type),
            joinedload(Request.requester),
            joinedload(Request.approvals).joinedload(RequestApproval.reviewer),
            joinedload(Request.history).joinedload(RequestHistory.actor),
        )
        .join(User, Request.requester_id == User.id)
        .join(Role, User.role_id == Role.id)
        .where(
            Request.status == "APPROVED",
            Role.code.in_(("EMPLOYEE", "DEPARTMENT_MANAGER")),
        )
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    return [serialize_request(r) for r in db.scalars(q).unique().all()]


@app.get("/api/requests/{request_id}")
def get_request(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.scalar(select(Request).options(joinedload(Request.request_type), joinedload(Request.requester), joinedload(Request.approvals).joinedload(RequestApproval.reviewer), joinedload(Request.history).joinedload(RequestHistory.actor)).where(Request.id == request_id))
    if not r: raise HTTPException(404, "الطلب غير موجود")
    if user.role.code == "EMPLOYEE":
        owns_request = r.requester_id == user.id
        is_drawing_inbox = user.department and user.department.name == "Drawing" and r.requester.department and r.requester.department.name == "فني مصنع" and r.status == "PENDING_DRAWING"
        if not owns_request and not is_drawing_inbox: raise HTTPException(403, "غير مسموح")
        return serialize_request(r)
    if user.role.code == "DEPARTMENT_MANAGER":
        owns_request = r.requester_id == user.id
        can_review = r.status == pending_status(user.role.code) and is_department_manager_for_request(user, r)
        if not owns_request and not can_review:
            raise HTTPException(403, "الطلب ليس لقسمك أو ليس في مرحلة صلاحيتك")
        if owns_request:
            return serialize_request(r)
    if user.role.code not in {"EMPLOYEE", "HR", "ADMIN"} and r.status != pending_status(user.role.code): raise HTTPException(403, "الطلب ليس في مرحلة صلاحيتك")
    return serialize_request(r)


@app.post("/api/requests/{request_id}/decision")
def decide(request_id: int, data: DecisionInput, user: User = Depends(require_roles("EXECUTIVE_MANAGER", "DEPARTMENT_MANAGER", "EMPLOYEE", "HR", "ADMIN")), db: Session = Depends(get_db)):
    if data.action not in {"APPROVE", "REJECT"}: raise HTTPException(422, "الإجراء يجب أن يكون APPROVE أو REJECT")
    r = db.scalar(select(Request).options(joinedload(Request.request_type), joinedload(Request.requester)).where(Request.id == request_id))
    if not r: raise HTTPException(404, "الطلب غير موجود")
    workflow = db.scalar(select(Workflow).options(joinedload(Workflow.steps)).where(Workflow.request_type_id == r.request_type_id))
    steps = approval_steps(r, workflow)
    current = next(((position, role_code) for position, role_code in steps if position == r.current_step), None)
    expected = current[1] if current else None
    if not current or r.status != pending_status(expected): raise HTTPException(409, "تم اتخاذ قرار على هذا الطلب مسبقاً")
    is_drawing_reviewer = expected == "DRAWING" and user.role.code == "EMPLOYEE" and user.department and user.department.name == "Drawing" and r.requester.department and r.requester.department.name == "فني مصنع"
    if expected != user.role.code and user.role.code != "ADMIN" and not is_drawing_reviewer: raise HTTPException(403, "الطلب ليس في مرحلة صلاحيتك")
    if expected == "DEPARTMENT_MANAGER" and user.role.code != "ADMIN" and not is_department_manager_for_request(user, r): raise HTTPException(403, "الطلب ليس لقسمك")
    if data.action == "REJECT" and not data.comment: raise HTTPException(422, "سبب الرفض مطلوب")
    db.add(RequestApproval(request_id=r.id, step_position=r.current_step or 0, reviewer_id=user.id, action=data.action, comment=data.comment))
    if data.action == "REJECT":
        r.status = rejected_status(expected); r.current_step = None
        log(db, r, user, f"{expected}_REJECTED", data.comment); replace_notification(db, r.requester_id, r, f"تم رفض الطلب #{r.id}: {data.comment}")
    else:
        next_step = next(((position, role_code) for position, role_code in steps if position > current[0]), None)
        if next_step:
            next_position, next_role = next_step
            r.status = pending_status(next_role); r.current_step = next_position
            log(db, r, user, f"{expected}_APPROVED", data.comment); notify_approver(db, next_role, r, f"طلب #{r.id} بانتظار موافقتك")
        else:
            r.status = "APPROVED"; r.current_step = None; log(db, r, user, f"{expected}_APPROVED", data.comment); replace_notification(db, r.requester_id, r, f"تمت الموافقة النهائية على الطلب #{r.id}")
    db.commit(); return {"id": r.id, "status": r.status, "status_label": status_label(r.status)}


@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Request)
    if user.role.code == "EMPLOYEE":
        if user.department and user.department.name == "Drawing":
            factory_department_id = db.scalar(select(Department.id).where(Department.name == "فني مصنع"))
            if factory_department_id is not None:
                drawing_requests = and_(Request.status == "PENDING_DRAWING", Request.requester.has(User.department_id == factory_department_id))
                q = q.where(or_(Request.requester_id == user.id, drawing_requests))
            else:
                q = q.where(Request.requester_id == user.id)
        else:
            q = q.where(Request.requester_id == user.id)
    elif user.role.code == "DEPARTMENT_MANAGER":
        q = q.where(or_(Request.requester_id == user.id, department_manager_inbox_filter(user)))
    elif user.role.code == "HR":
        q = q.where(or_(Request.requester_id == user.id, Request.status == pending_status(user.role.code)))
    elif user.role.code != "ADMIN": q = q.where(Request.status == pending_status(user.role.code))
    rows = db.scalars(q).all(); counts = {s: sum(r.status == s for r in rows) for s in STATUS}
    return {"total":len(rows), "counts":counts, "unread_notifications": db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id == user.id, Notification.read.is_(False))) or 0}


@app.get("/api/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    latest = db.scalar(
        select(Notification)
        .where(Notification.recipient_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(1)
    )
    if latest is None:
        return []
    db.execute(delete(Notification).where(Notification.recipient_id == user.id, Notification.id != latest.id))
    db.commit()
    return [{"id": latest.id, "message": latest.message, "request_id": latest.request_id, "read": latest.read, "created_at": latest.created_at}]


@app.get("/api/admin/roles")
def admin_roles(_: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    return [{"code": role.code, "name_ar": role.name_ar} for role in db.scalars(select(Role).order_by(Role.code)).all()]


@app.get("/api/admin/users")
def admin_users(_: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).options(joinedload(User.role), joinedload(User.department)).order_by(User.id)).all()
    return [{"id": u.id, "full_name": u.full_name, "employee_id": u.employee_id, "email": u.email, "active": u.active, "registration_status": u.registration_status, "role": u.role.code, "role_name": u.role.name_ar, "department": u.department.name if u.department else None} for u in users]


@app.post("/api/admin/users/{user_id}/registration-decision")
def admin_decide_registration(user_id: int, data: RegistrationDecisionInput, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "المستخدم غير موجود")
    if user.role.code != "DEPARTMENT_MANAGER": raise HTTPException(422, "هذا الإجراء مخصص لمسؤولي الأقسام")
    if user.registration_status != "PENDING": raise HTTPException(409, "تم اتخاذ قرار على طلب الحساب مسبقًا")
    approved = data.action == "APPROVE"
    user.registration_status = "APPROVED" if approved else "REJECTED"
    user.active = approved
    db.commit()
    return {"id": user.id, "registration_status": user.registration_status, "active": user.active}


@app.post("/api/admin/users", status_code=201)
def admin_create_user(data: UserCreateInput, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    role = db.scalar(select(Role).where(Role.code == data.role_code))
    if not role: raise HTTPException(422, "الدور غير موجود")
    if db.scalar(select(User).where((User.email == data.email) | (User.employee_id == data.employee_id))): raise HTTPException(409, "البريد أو الرقم الوظيفي مستخدم بالفعل")
    validate_department_assignment(db, data.role_code, data.department_id)
    user = User(full_name=data.full_name, employee_id=data.employee_id, email=data.email, password_hash=hash_password(data.password), role_id=role.id, department_id=data.department_id)
    db.add(user); db.commit(); db.refresh(user)
    return {"id": user.id, "email": user.email, "role": role.code, "active": user.active}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, data: UserUpdateInput, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "المستخدم غير موجود")
    if user.id == actor.id and data.active is False: raise HTTPException(422, "لا يمكن تعطيل حسابك الحالي")
    if user.registration_status in {"PENDING", "REJECTED"} and data.active is True: raise HTTPException(422, "يجب اتخاذ قرار الموافقة على طلب مسؤول القسم أولًا")
    role_code = data.role_code or user.role.code
    department_id = data.department_id if "department_id" in data.model_fields_set else user.department_id
    validate_department_assignment(db, role_code, department_id)
    if data.role_code:
        role = db.scalar(select(Role).where(Role.code == role_code))
        if not role: raise HTTPException(422, "الدور غير موجود")
        user.role_id = role.id
    for field in ("full_name", "email", "active"):
        value = getattr(data, field)
        if value is not None: setattr(user, field, value)
    if "department_id" in data.model_fields_set: user.department_id = data.department_id
    if data.password: user.password_hash = hash_password(data.password)
    db.commit(); return {"id": user.id, "email": user.email, "active": user.active}


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_user_password(user_id: int, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if not user.active:
        raise HTTPException(409, "فعّل الحساب قبل إعادة تعيين كلمة المرور")
    new_password = secrets.token_urlsafe(18)
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"id": user.id, "email": user.email, "temporary_password": new_password}


@app.get("/api/admin/departments")
def admin_departments(_: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).order_by(Department.name)).all()]


@app.post("/api/admin/departments", status_code=201)
def admin_create_department(data: DepartmentInput, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.scalar(select(Department).where(Department.name == data.name)): raise HTTPException(409, "القسم موجود بالفعل")
    department = Department(name=data.name); db.add(department); db.commit(); db.refresh(department)
    return {"id": department.id, "name": department.name}


@app.get("/api/admin/request-types")
def admin_request_types(_: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    return [{"id": r.id, "code": r.code, "name_ar": r.name_ar, "fields": r.fields, "active": r.active} for r in db.scalars(select(RequestType).order_by(RequestType.code)).all()]


@app.post("/api/admin/request-types", status_code=201)
def admin_create_request_type(data: RequestTypeInput, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.scalar(select(RequestType).where(RequestType.code == data.code)): raise HTTPException(409, "نوع الطلب موجود بالفعل")
    if not data.workflow_roles: raise HTTPException(422, "يجب تعريف خطوة موافقة واحدة على الأقل")
    request_type = RequestType(code=data.code, name_ar=data.name_ar, fields=data.fields, active=data.active); db.add(request_type); db.flush()
    workflow = Workflow(request_type_id=request_type.id, name=f"مسار {data.name_ar}"); db.add(workflow); db.flush()
    db.add_all([WorkflowStep(workflow_id=workflow.id, position=position, role_code=role_code, label_ar=role_code) for position, role_code in enumerate(data.workflow_roles, 1)])
    db.commit(); return {"id": request_type.id, "code": request_type.code}


@app.patch("/api/admin/request-types/{request_type_id}")
def admin_update_request_type(request_type_id: int, data: RequestTypeInput, _: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    request_type = db.get(RequestType, request_type_id)
    if not request_type: raise HTTPException(404, "نوع الطلب غير موجود")
    request_type.code = data.code; request_type.name_ar = data.name_ar; request_type.fields = data.fields; request_type.active = data.active
    db.commit(); return {"id": request_type.id, "code": request_type.code, "active": request_type.active}


@app.get("/api/admin/audit")
def admin_audit(_: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RequestHistory).options(joinedload(RequestHistory.actor)).order_by(RequestHistory.created_at.desc())).all()
    return [{"request_id": row.request_id, "action": row.action, "comment": row.comment, "role": row.actor_role, "actor": row.actor.full_name if row.actor else None, "at": row.created_at} for row in rows]
