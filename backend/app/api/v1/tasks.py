from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user_id
from app.db.database import get_db
from app.schemas.task import TASK_PRIORITIES, TASK_STATUSES, TaskInput, TaskResponse, TaskUpdate
from app.services.task_service import create_task, delete_task, get_task_for_user, is_overdue, list_tasks, update_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def response_for(task):
    return TaskResponse.model_validate(task).model_copy(update={"is_overdue": is_overdue(task)})


@router.get("", response_model=list[TaskResponse])
def get_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    category: str | None = Query(default=None),
    overdue: bool | None = Query(default=None),
    sort: str = Query(default="deadline", pattern="^(deadline|created|priority|title)$"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[TaskResponse]:
    if priority is not None and priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="invalid priority")
    try:
        tasks = list_tasks(db, user_id, status=status_filter, priority=priority, category=category, overdue=overdue, sort=sort)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return [response_for(task) for task in tasks]


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def add_task(payload: TaskInput, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> TaskResponse:
    try:
        return response_for(create_task(db, user_id, payload))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/{task_id}", response_model=TaskResponse)
def edit_task(task_id: int, payload: TaskUpdate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> TaskResponse:
    task = get_task_for_user(db, user_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        return response_for(update_task(db, task, payload))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_task(task_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> None:
    task = get_task_for_user(db, user_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        delete_task(db, task)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
