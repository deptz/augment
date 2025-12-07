"""
Team Member Service
Service for managing team members, teams, and boards with many-to-many relationships
"""
import sqlite3
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime

from .team_member_db import get_db_connection

logger = logging.getLogger(__name__)


class TeamMemberService:
    """Service for team member CRUD operations"""
    
    def get_member(self, member_id: int) -> Optional[Dict[str, Any]]:
        """Get member by ID with teams"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM members WHERE id = ?
            """, (member_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            member = dict(row)
            
            # Get teams for this member
            cursor.execute("""
                SELECT t.id, t.name, t.description, mt.role, mt.capacity_allocation
                FROM teams t
                JOIN member_teams mt ON t.id = mt.team_id
                WHERE mt.member_id = ? AND mt.is_active = 1 AND t.is_active = 1
            """, (member_id,))
            teams = [dict(row) for row in cursor.fetchall()]
            member['teams'] = teams
            
            return member
        finally:
            conn.close()
    
    def get_members(self, team_id: Optional[int] = None, level: Optional[str] = None, 
                   active_only: bool = True) -> List[Dict[str, Any]]:
        """List members (optionally filtered)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT DISTINCT m.* FROM members m
            """
            conditions = []
            params = []
            
            if team_id:
                query += """
                    JOIN member_teams mt ON m.id = mt.member_id
                """
                conditions.append("mt.team_id = ? AND mt.is_active = 1")
                params.append(team_id)
            
            if level:
                conditions.append("m.level = ?")
                params.append(level)
            
            if active_only:
                conditions.append("m.is_active = 1")
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY m.name"
            
            cursor.execute(query, params)
            members = [dict(row) for row in cursor.fetchall()]
            
            # Get teams for each member
            for member in members:
                cursor.execute("""
                    SELECT t.id, t.name, t.description, mt.role, mt.capacity_allocation
                    FROM teams t
                    JOIN member_teams mt ON t.id = mt.team_id
                    WHERE mt.member_id = ? AND mt.is_active = 1 AND t.is_active = 1
                """, (member['id'],))
                member['teams'] = [dict(row) for row in cursor.fetchall()]
            
            return members
        finally:
            conn.close()
    
    def create_member(self, name: str, email: str, level: str, capacity_days_per_sprint: float,
                     team_ids: List[int], roles: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create member and assign to teams"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Insert member
            cursor.execute("""
                INSERT INTO members (name, email, level, capacity_days_per_sprint)
                VALUES (?, ?, ?, ?)
            """, (name, email, level, capacity_days_per_sprint))
            member_id = cursor.lastrowid
            
            # Assign to teams
            if team_ids:
                for idx, team_id in enumerate(team_ids):
                    role = roles[idx] if roles and idx < len(roles) else None
                    cursor.execute("""
                        INSERT INTO member_teams (member_id, team_id, role)
                        VALUES (?, ?, ?)
                    """, (member_id, team_id, role))
            
            conn.commit()
            logger.info(f"✅ Created member {member_id}: {name}")
            return self.get_member(member_id)
        except sqlite3.IntegrityError as e:
            conn.rollback()
            logger.error(f"❌ Failed to create member: {str(e)}")
            raise ValueError(f"Member with email {email} already exists")
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to create member: {str(e)}")
            raise
        finally:
            conn.close()
    
    def update_member(self, member_id: int, **kwargs) -> Dict[str, Any]:
        """Update member"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            allowed_fields = ['name', 'email', 'level', 'capacity_days_per_sprint', 'is_active']
            updates = []
            params = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    updates.append(f"{field} = ?")
                    params.append(value)
            
            if not updates:
                return self.get_member(member_id)
            
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(member_id)
            
            query = f"UPDATE members SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            
            logger.info(f"✅ Updated member {member_id}")
            return self.get_member(member_id)
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to update member {member_id}: {str(e)}")
            raise
        finally:
            conn.close()
    
    def assign_member_to_teams(self, member_id: int, team_ids: List[int], 
                               roles: Optional[List[str]] = None) -> bool:
        """Assign member to teams"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            for idx, team_id in enumerate(team_ids):
                role = roles[idx] if roles and idx < len(roles) else None
                cursor.execute("""
                    INSERT OR REPLACE INTO member_teams (member_id, team_id, role, is_active)
                    VALUES (?, ?, ?, 1)
                """, (member_id, team_id, role))
            
            conn.commit()
            logger.info(f"✅ Assigned member {member_id} to {len(team_ids)} teams")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to assign member to teams: {str(e)}")
            raise
        finally:
            conn.close()
    
    def remove_member_from_teams(self, member_id: int, team_ids: List[int]) -> bool:
        """Remove member from teams"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE member_teams 
                SET is_active = 0 
                WHERE member_id = ? AND team_id IN ({})
            """.format(','.join('?' * len(team_ids))), [member_id] + team_ids)
            
            conn.commit()
            logger.info(f"✅ Removed member {member_id} from {len(team_ids)} teams")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to remove member from teams: {str(e)}")
            raise
        finally:
            conn.close()
    
    def delete_member(self, member_id: int) -> bool:
        """Soft delete (set is_active=False)"""
        return self.update_member(member_id, is_active=False) is not None
    
    def get_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Get team by ID with members and boards"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            team = dict(row)
            
            # Get members
            cursor.execute("""
                SELECT m.id, m.name, m.email, m.level, mt.role, mt.capacity_allocation
                FROM members m
                JOIN member_teams mt ON m.id = mt.member_id
                WHERE mt.team_id = ? AND mt.is_active = 1 AND m.is_active = 1
            """, (team_id,))
            team['members'] = [dict(row) for row in cursor.fetchall()]
            
            # Get boards
            cursor.execute("""
                SELECT b.id, b.jira_board_id, b.name, b.project_key
                FROM boards b
                JOIN team_boards tb ON b.id = tb.board_id
                WHERE tb.team_id = ? AND tb.is_active = 1 AND b.is_active = 1
            """, (team_id,))
            team['boards'] = [dict(row) for row in cursor.fetchall()]
            
            return team
        finally:
            conn.close()
    
    def get_teams(self, board_id: Optional[int] = None, active_only: bool = True) -> List[Dict[str, Any]]:
        """List teams (optionally filtered by board)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT DISTINCT t.* FROM teams t"
            conditions = []
            params = []
            
            if board_id:
                query += " JOIN team_boards tb ON t.id = tb.team_id"
                conditions.append("tb.board_id = ? AND tb.is_active = 1")
                params.append(board_id)
            
            if active_only:
                conditions.append("t.is_active = 1")
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY t.name"
            
            cursor.execute(query, params)
            teams = [dict(row) for row in cursor.fetchall()]
            
            # Get member and board counts for each team
            for team in teams:
                cursor.execute("""
                    SELECT COUNT(*) as member_count
                    FROM member_teams
                    WHERE team_id = ? AND is_active = 1
                """, (team['id'],))
                team['member_count'] = cursor.fetchone()['member_count']
                
                cursor.execute("""
                    SELECT COUNT(*) as board_count
                    FROM team_boards
                    WHERE team_id = ? AND is_active = 1
                """, (team['id'],))
                team['board_count'] = cursor.fetchone()['board_count']
            
            return teams
        finally:
            conn.close()
    
    def create_team(self, name: str, description: Optional[str] = None, 
                   board_ids: List[int] = []) -> Dict[str, Any]:
        """Create team and assign to boards"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO teams (name, description)
                VALUES (?, ?)
            """, (name, description))
            team_id = cursor.lastrowid
            
            # Assign to boards
            for board_id in board_ids:
                cursor.execute("""
                    INSERT INTO team_boards (team_id, board_id)
                    VALUES (?, ?)
                """, (team_id, board_id))
            
            conn.commit()
            logger.info(f"✅ Created team {team_id}: {name}")
            return self.get_team(team_id)
        except sqlite3.IntegrityError as e:
            conn.rollback()
            logger.error(f"❌ Failed to create team: {str(e)}")
            raise ValueError(f"Team with name {name} already exists")
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to create team: {str(e)}")
            raise
        finally:
            conn.close()
    
    def assign_team_to_boards(self, team_id: int, board_ids: List[int]) -> bool:
        """Assign team to boards"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            for board_id in board_ids:
                cursor.execute("""
                    INSERT OR REPLACE INTO team_boards (team_id, board_id, is_active)
                    VALUES (?, ?, 1)
                """, (team_id, board_id))
            
            conn.commit()
            logger.info(f"✅ Assigned team {team_id} to {len(board_ids)} boards")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to assign team to boards: {str(e)}")
            raise
        finally:
            conn.close()
    
    def remove_team_from_boards(self, team_id: int, board_ids: List[int]) -> bool:
        """Remove team from boards"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE team_boards 
                SET is_active = 0 
                WHERE team_id = ? AND board_id IN ({})
            """.format(','.join('?' * len(board_ids))), [team_id] + board_ids)
            
            conn.commit()
            logger.info(f"✅ Removed team {team_id} from {len(board_ids)} boards")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Failed to remove team from boards: {str(e)}")
            raise
        finally:
            conn.close()
    
    def get_team_capacity(self, team_id: int, board_id: Optional[int] = None) -> float:
        """Get total capacity for a team (sum of active members, optionally filtered by board)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT SUM(m.capacity_days_per_sprint * COALESCE(mt.capacity_allocation, 1.0)) as total_capacity
                FROM members m
                JOIN member_teams mt ON m.id = mt.member_id
                WHERE mt.team_id = ? AND mt.is_active = 1 AND m.is_active = 1
            """
            params = [team_id]
            
            if board_id:
                query += """
                    AND EXISTS (
                        SELECT 1 FROM team_boards tb
                        WHERE tb.team_id = mt.team_id 
                        AND tb.board_id = ? 
                        AND tb.is_active = 1
                    )
                """
                params.append(board_id)
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            capacity = result['total_capacity'] if result and result['total_capacity'] else 0.0
            return capacity
        finally:
            conn.close()
    
    def get_board_teams(self, board_id: int) -> List[Dict[str, Any]]:
        """Get all teams assigned to a board"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT t.* FROM teams t
                JOIN team_boards tb ON t.id = tb.team_id
                WHERE tb.board_id = ? AND tb.is_active = 1 AND t.is_active = 1
                ORDER BY t.name
            """, (board_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_member_teams(self, member_id: int) -> List[Dict[str, Any]]:
        """Get all teams a member belongs to"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT t.*, mt.role, mt.capacity_allocation
                FROM teams t
                JOIN member_teams mt ON t.id = mt.team_id
                WHERE mt.member_id = ? AND mt.is_active = 1 AND t.is_active = 1
                ORDER BY t.name
            """, (member_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_all_levels(self) -> List[str]:
        """Get list of all career levels"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT DISTINCT level FROM members WHERE is_active = 1 ORDER BY level")
            return [row['level'] for row in cursor.fetchall()]
        finally:
            conn.close()


