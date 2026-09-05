import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import ModerationAudit, Report, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Закрытые команды модерации SPORTS MATE")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reports")
    block = sub.add_parser("block-user")
    block.add_argument("user_id")
    block.add_argument("--moderator-id", required=True)
    block.add_argument("--reason", required=True)
    resolve = sub.add_parser("resolve-report")
    resolve.add_argument("report_id")
    resolve.add_argument("--moderator-id", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command == "reports":
            for item in db.scalars(
                select(Report).where(Report.status == "new").order_by(Report.created_at)
            ):
                print(item.id, item.reason, item.target_id, item.activity_id or "-")
            return
        moderator = db.get(User, args.moderator_id)
        if not moderator or not moderator.is_moderator:
            raise SystemExit("Указанный пользователь не является модератором")
        if args.command == "block-user":
            target = db.get(User, args.user_id)
            if not target:
                raise SystemExit("Пользователь не найден")
            target.globally_blocked_at = datetime.now(timezone.utc)
            db.add(
                ModerationAudit(
                    moderator_id=moderator.id,
                    target_id=target.id,
                    action="global_block",
                    reason=args.reason,
                )
            )
        else:
            report = db.get(Report, args.report_id)
            if not report:
                raise SystemExit("Жалоба не найдена")
            report.status = "resolved"
            db.add(
                ModerationAudit(
                    moderator_id=moderator.id,
                    target_id=report.target_id,
                    action="resolve_report",
                    reason=report.reason,
                )
            )
        db.commit()


if __name__ == "__main__":
    main()
