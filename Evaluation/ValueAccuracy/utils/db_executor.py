import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DBExecutor:
    """
    Executes SQL queries against the PostgreSQL database to fetch Ground Truth values.
    """
    def __init__(self):
        self.host = os.getenv("POSTGRES_HOST", "localhost")
        self.port = os.getenv("POSTGRES_PORT", "5432")
        self.dbname = os.getenv("POSTGRES_DB", "medical_data")
        self.user = os.getenv("POSTGRES_USER", "postgres")
        self.password = os.getenv("POSTGRES_PASSWORD", "")
        self.conn = None

    def connect(self):
        """Establish a connection to the database."""
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    dbname=self.dbname,
                    user=self.user,
                    password=self.password
                )
                # Set read-only to prevent accidental modifications during evaluation
                self.conn.set_session(readonly=True, autocommit=True)
                logger.debug("Successfully connected to the database.")
            except Exception as e:
                logger.error(f"Failed to connect to the database: {e}")
                raise

    def close(self):
        """Close the database connection."""
        if self.conn is not None and not self.conn.closed:
            self.conn.close()
            logger.debug("Database connection closed.")

    def execute_query(self, query: str) -> dict:
        """
        Executes a SELECT query and returns the result.
        
        Args:
            query (str): The SQL query to execute.
            
        Returns:
            dict: A dictionary containing:
                - 'success' (bool): Whether the query executed successfully.
                - 'result' (list or any): The fetched data if successful.
                - 'error' (str): Error message if execution failed.
        """
        self.connect()
        
        # Basic safety check: ensure it starts with SELECT or WITH (for CTEs)
        query_upper = query.strip().upper()
        if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
            return {
                "success": False,
                "result": None,
                "error": "Only SELECT or WITH queries are allowed for Ground Truth generation."
            }

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                
                # Convert RealDictRow to standard dict
                formatted_results = [dict(row) for row in results]
                
                return {
                    "success": True,
                    "result": formatted_results,
                    "error": None
                }
        except Exception as e:
            # Rollback is handled by autocommit/readonly session, but good practice
            if self.conn and not self.conn.closed:
                 self.conn.rollback()
            logger.warning(f"Query execution failed: {e}\nQuery: {query}")
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }

    def get_single_value(self, query: str):
        """
        Executes a query expected to return a single scalar value (e.g., COUNT, AVG).
        """
        response = self.execute_query(query)
        if not response["success"]:
            return response
            
        results = response["result"]
        if not results:
            return {"success": True, "result": None, "error": "No rows returned."}
            
        if len(results) > 1:
            return {"success": False, "result": None, "error": "Query returned multiple rows, expected a single value."}
            
        row = results[0]
        if len(row) > 1:
            return {"success": False, "result": None, "error": "Query returned multiple columns, expected a single scalar value."}
            
        # Get the first (and only) value from the dictionary
        single_value = list(row.values())[0]
        
        return {
            "success": True,
            "result": single_value,
            "error": None
        }

# Simple test if run directly
if __name__ == "__main__":
    executor = DBExecutor()
    print("Testing connection and simple query...")
    res = executor.get_single_value("SELECT COUNT(*) FROM parameter;")
    print(f"Total parameters in DB: {res}")
    
    res2 = executor.execute_query("SELECT param_key, concept_category FROM parameter LIMIT 2;")
    print(f"Sample parameters: {res2}")
    executor.close()
