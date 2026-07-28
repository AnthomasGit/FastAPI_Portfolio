from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import Project, Scene, Character, Location, Prop, scene_characters, scene_locations, scene_props


async def save_storyboard(db: AsyncSession, project_id: str, storyboard_data: dict):
    project = await db.get(Project, project_id)
    project.title = storyboard_data.get("title", project.title)
    project.story_summary = storyboard_data.get("story_summary", "")
    project.status = "complete"

    char_cache = {}

    for scene_data in storyboard_data.get("scenes", []):
        scene = Scene(
            project_id=project_id,
            scene_number=scene_data["scene_number"],
            slugline=scene_data.get("slugline", ""),
            screenplay=scene_data.get("screenplay", ""),
            sort_order=scene_data["scene_number"]
        )
        db.add(scene)
        await db.flush()

        for char_data in scene_data.get("characters", []):
            name = char_data["name"]
            if name not in char_cache:
                char = Character(
                    project_id=project_id,
                    name=name,
                    description=char_data.get("description", ""),
                    traits=char_data.get("traits", {})
                )
                db.add(char)
                await db.flush()
                char_cache[name] = char
            await db.execute(scene_characters.insert().values(scene_id=scene.id, character_id=char_cache[name].id))

        for loc_data in scene_data.get("locations", []):
            result = await db.execute(
                select(Location).where(Location.project_id == project_id, Location.name == loc_data["name"])
            )
            loc = result.scalars().first()
            if not loc:
                loc = Location(
                    project_id=project_id,
                    name=loc_data["name"],
                    description=loc_data.get("description", ""),
                    shot_notes=loc_data.get("shot_notes", "")
                )
                db.add(loc)
                await db.flush()
            await db.execute(scene_locations.insert().values(scene_id=scene.id, location_id=loc.id))

        for prop_data in scene_data.get("props", []):
            result = await db.execute(
                select(Prop).where(Prop.project_id == project_id, Prop.name == prop_data["name"])
            )
            prop = result.scalars().first()
            if not prop:
                prop = Prop(
                    project_id=project_id,
                    name=prop_data["name"],
                    description=prop_data.get("description", "")
                )
                db.add(prop)
                await db.flush()
            await db.execute(scene_props.insert().values(scene_id=scene.id, prop_id=prop.id))

    await db.commit()
