from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthenticatedIdentity
from app.modules.workspaces.infrastructure.models import User, UserIdentity


async def resolve_user(session: AsyncSession, identity: AuthenticatedIdentity) -> User:
    statement = (
        select(UserIdentity)
        .where(
            UserIdentity.provider == identity.provider,
            UserIdentity.provider_subject == identity.subject,
        )
        .options(selectinload(UserIdentity.user))
    )
    existing = (await session.exec(statement)).one_or_none()
    if existing is not None:
        return existing.user

    user = User(email=identity.email, display_name=identity.display_name)
    user.identities.append(
        UserIdentity(
            provider=identity.provider,
            provider_subject=identity.subject,
            email_at_link_time=identity.email,
        )
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
