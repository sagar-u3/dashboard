import os
import json
import yaml
import subprocess
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging
import uvicorn

# Configuration
DOCKER_COMPOSE_PATH = os.getenv('DOCKER_COMPOSE_PATH', os.path.join(os.getcwd(), 'docker-compose.yml'))
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Dashboard", description="System management dashboard with command execution")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

class CommandRequest(BaseModel):
    command: str
    timeout: int = 30

class CommandResponse(BaseModel):
    output: str
    error: str
    return_code: int
    command: str

# Store active terminal sessions
terminal_sessions = {}

def is_command_safe(command: str) -> tuple[bool, str]:
    """Check if command is safe to execute"""
    # All commands are now allowed
    return True, "Command is allowed"

class TerminalSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.process = None
        self.cwd = os.path.expanduser("~")  # Start in user's home directory
        
    async def execute_command(self, command: str):
        """Execute command in terminal session"""
        try:
            # Change to working directory and execute command
            full_command = f"cd {self.cwd} && {command}"
            
            # For cd commands, update working directory
            if command.strip().startswith("cd "):
                new_dir = command.strip()[3:].strip()
                if new_dir == "~":
                    self.cwd = os.path.expanduser("~")
                elif new_dir.startswith("/"):
                    self.cwd = new_dir
                else:
                    self.cwd = os.path.join(self.cwd, new_dir)
                return f"Changed directory to {self.cwd}"
            
            # Execute command
            process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            stdout, stderr = await process.communicate()
            
            output = stdout.decode('utf-8', errors='replace').strip()
            error = stderr.decode('utf-8', errors='replace').strip()
            
            if output:
                return output
            elif error:
                return f"Error: {error}"
            else:
                return "Command executed successfully"
                
        except Exception as e:
            return f"Error: {str(e)}"

@app.websocket("/ws/terminal/{session_id}")
async def websocket_terminal(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for terminal session"""
    await websocket.accept()
    
    # Create or get terminal session
    if session_id not in terminal_sessions:
        terminal_sessions[session_id] = TerminalSession(session_id)
    
    session = terminal_sessions[session_id]
    
    try:
        while True:
            # Receive command from client
            data = await websocket.receive_text()
            try:
                print(f"Received raw data: {data}")
                command_data = json.loads(data)
                command = command_data.get("command", "")
                print(f"Parsed command: {command}")
                
                if not command:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "No command received"
                    }))
                    continue
                
                if command.lower() in ["exit", "quit"]:
                    await websocket.send_text(json.dumps({
                        "type": "system",
                        "message": "Terminal session ended"
                    }))
                    break
                
                # Execute command
                result = await session.execute_command(command)
                
                # Send result back to client (don't echo command, frontend already shows it)
                response_data = {
                    "type": "output",
                    "command": command,  # Include command in response for frontend display
                    "result": result,
                    "cwd": session.cwd
                }
                print(f"Sending response: {response_data}")
                await websocket.send_text(json.dumps(response_data))
                
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "error", 
                    "message": str(e)
                }))
                
    except WebSocketDisconnect:
        # Clean up session
        if session_id in terminal_sessions:
            del terminal_sessions[session_id]

@app.get("/")
async def get_web_interface():
    """Serve the web interface"""
    return FileResponse('static/index.html')

@app.post("/execute", response_model=CommandResponse)
async def execute_command(request: CommandRequest):
    """Execute a Linux command"""
    command = request.command.strip()
    
    if not command:
        raise HTTPException(status_code=400, detail="Command cannot be empty")
    
    # Security check
    is_safe, safety_message = is_command_safe(command)
    if not is_safe:
        raise HTTPException(status_code=403, detail=safety_message)
    
    try:
        # Execute command with timeout
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout
            )
            
            output = stdout.decode('utf-8', errors='replace').strip()
            error = stderr.decode('utf-8', errors='replace').strip()
            
            return CommandResponse(
                output=output,
                error=error,
                return_code=process.returncode,
                command=command
            )
            
        except asyncio.TimeoutError:
            # Kill the process if it times out
            try:
                process.kill()
                await process.wait()
            except:
                pass
            
            raise HTTPException(
                status_code=408,
                detail=f"Command timed out after {request.timeout} seconds"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing command: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "dashboard"}

# Docker API endpoints
@app.get("/api/docker/compose")
async def get_docker_compose():
    """Read Docker Compose file from environment path"""
    try:
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"error": f"Docker Compose file not found: {DOCKER_COMPOSE_PATH}"}
        
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            content = f.read()
        
        return {
            "content": content,
            "path": DOCKER_COMPOSE_PATH,
            "exists": True
        }
    except Exception as e:
        return {"error": f"Error reading Docker Compose file: {str(e)}"}

@app.get("/api/docker/status")
async def get_docker_status():
    """Get Docker container status"""
    try:
        # Change to directory containing docker-compose file
        compose_dir = os.path.dirname(DOCKER_COMPOSE_PATH)
        result = subprocess.run(['docker', 'compose', 'ps', '--format', 'json'], 
                              cwd=compose_dir,
                              capture_output=True, text=True, check=True)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                container_data = json.loads(line)
                # Add the service name as a separate field for easier matching
                if 'Service' in container_data:
                    container_data['service_name'] = container_data['Service']
                containers.append(container_data)
        return {"containers": containers}
    except subprocess.CalledProcessError as e:
        return {"error": f"Docker command failed: {e}"}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

@app.post("/api/docker/start/{service_name}")
async def start_service(service_name: str):
    """Start Docker service"""
    try:
        # Change to directory containing docker-compose file
        compose_dir = os.path.dirname(DOCKER_COMPOSE_PATH)
        result = subprocess.run(['docker', 'compose', 'up', '-d', service_name], 
                              cwd=compose_dir,
                              capture_output=True, text=True, check=True)
        return {"success": True, "message": f"Service {service_name} started"}
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start {service_name}: {e.stderr}",exc_info=True)
        return {"success": False, "error": f"Failed to start {service_name}: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error occurred: {str(e)}",exc_info=True)
        return {"success": False, "error": f"Error: {str(e)}"}

@app.post("/api/docker/stop/{service_name}")
async def stop_service(service_name: str):
    """Stop Docker service"""
    try:
        # Change to directory containing docker-compose file
        compose_dir = os.path.dirname(DOCKER_COMPOSE_PATH)
        result = subprocess.run(['docker', 'compose', 'stop', service_name], 
                              cwd=compose_dir,
                              capture_output=True, text=True, check=True)
        return {"success": True, "message": f"Service {service_name} stopped"}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to stop {service_name}: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}

@app.post("/api/docker/restart/{service_name}")
async def restart_service(service_name: str):
    """Restart Docker service"""
    try:
        # Change to directory containing docker-compose file
        compose_dir = os.path.dirname(DOCKER_COMPOSE_PATH)
        result = subprocess.run(['docker', 'compose', 'restart', service_name], 
                              cwd=compose_dir,
                              capture_output=True, text=True, check=True)
        return {"success": True, "message": f"Service {service_name} restarted"}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": f"Failed to restart {service_name}: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}

@app.get("/api/docker/logs/{service_name}")
async def get_service_logs(service_name: str):
    """Get Docker service logs"""
    try:
        # Change to directory containing docker-compose file
        compose_dir = os.path.dirname(DOCKER_COMPOSE_PATH)
        result = subprocess.run(['docker', 'compose', 'logs', '--tail=100', service_name], 
                              cwd=compose_dir,
                              capture_output=True, text=True, check=True)
        return {"logs": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to get logs for {service_name}: {e}"}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

@app.get("/api/docker/get-service/{service_name}")
async def get_service(service_name: str):
    """Get details of a specific service from Docker Compose file"""
    try:
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"error": f"Docker Compose file not found: {DOCKER_COMPOSE_PATH}"}
        
        # Parse YAML file
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        # Check if services section exists
        if 'services' not in compose_data:
            return {"error": "No services section found in docker-compose.yml"}
        
        # Check if service exists
        if service_name not in compose_data['services']:
            return {"error": f"Service {service_name} not found"}
        
        service_config = compose_data['services'][service_name]
        
        # Extract service data
        service_data = {
            'name': service_name,
            'image': service_config.get('image', ''),
            'build': service_config.get('build', None),
            'ports': [],
            'environment': {}
        }
        
        # Parse ports (keep as dict format)
        if 'ports' in service_config:
            ports = service_config['ports']
            if isinstance(ports, list):
                for port in ports:
                    if isinstance(port, dict):
                        port_dict = {
                            'published': port.get('published', ''),
                            'target': port.get('target', ''),
                            'protocol': port.get('protocol', 'tcp')
                        }
                        service_data['ports'].append(port_dict)
        
        # Parse environment (keep as dict format)
        if 'environment' in service_config:
            env = service_config['environment']
            if isinstance(env, dict):
                # Convert all values to strings, preserving boolean format
                service_data['environment'] = {}
                for k, v in env.items():
                    if isinstance(v, bool):
                        service_data['environment'][k] = str(v).lower()
                    else:
                        service_data['environment'][k] = str(v)
            elif isinstance(env, list):
                # Convert list format to dict
                for item in env:
                    if '=' in item:
                        key, value = item.split('=', 1)
                        service_data['environment'][key.strip()] = value.strip()
        
        return service_data
        
    except Exception as e:
        return {"error": f"Error getting service: {str(e)}"}

@app.post("/api/docker/add-service")
async def add_service(request: dict):
    """Add a new service to Docker Compose file"""
    try:
        service_name = request.get('name', '').strip()
        service_image = request.get('image', '').strip()
        service_build = request.get('build', None)
        service_ports = request.get('ports', [])
        service_env = request.get('environment', {})
        
        if not service_name or (not service_image and not service_build):
            return {"success": False, "error": "Service name and either image or build context are required"}
        
        # Read current compose file
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"success": False, "error": f"Docker Compose file not found: {DOCKER_COMPOSE_PATH}"}
        
        # Parse YAML file
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        # Check if services section exists
        if 'services' not in compose_data:
            compose_data['services'] = {}
        
        # Check if service already exists
        if service_name in compose_data['services']:
            return {"success": False, "error": f"Service {service_name} already exists"}
        
        # Build new service configuration
        new_service = {}
        if service_image:
            new_service['image'] = service_image
        if service_build is not None:
            if isinstance(service_build, dict):
                build_context = service_build.get('context', '').strip()
                if not build_context:
                    return {"success": False, "error": "Build context is required when build is provided"}
                build_config = {'context': build_context}
                dockerfile = service_build.get('dockerfile', '')
                if isinstance(dockerfile, str) and dockerfile.strip():
                    build_config['dockerfile'] = dockerfile.strip()
                args = service_build.get('args')
                if isinstance(args, dict) and args:
                    build_config['args'] = {k: str(v) for k, v in args.items()}
                target = service_build.get('target')
                if target is not None and str(target).strip():
                    build_config['target'] = str(target).strip()
                new_service['build'] = build_config
            elif isinstance(service_build, str) and service_build.strip():
                new_service['build'] = service_build.strip()
            else:
                return {"success": False, "error": "Build must be a valid string or object"}
        
        # Add ports if provided
        if service_ports and isinstance(service_ports, list):
            ports_list = []
            for port in service_ports:
                if isinstance(port, dict):
                    port_dict = {
                        'target': int(port.get('target', 0)),
                        'published': int(port.get('published', 0)),
                        'protocol': port.get('protocol', 'tcp')
                    }
                    ports_list.append(port_dict)
            if ports_list:
                new_service['ports'] = ports_list
        
        # Add environment variables if provided
        if service_env and isinstance(service_env, dict):
            env_dict = {}
            for key, value in service_env.items():
                if key.strip() and value is not None:
                    env_dict[key.strip()] = str(value).strip()
            if env_dict:
                new_service['environment'] = env_dict
        
        # Add the new service
        compose_data['services'][service_name] = new_service
        
        # Write back to file
        with open(DOCKER_COMPOSE_PATH, 'w') as f:
            yaml.safe_dump(compose_data, f, default_flow_style=False, sort_keys=False)
        
        return {"success": True, "message": f"Service {service_name} added successfully"}
        
    except Exception as e:
        return {"success": False, "error": f"Error adding service: {str(e)}"}

@app.put("/api/docker/update-service/{service_name}")
async def update_service(service_name: str, request: dict):
    """Update an existing service in Docker Compose file"""
    try:
        service_image = request.get('image', None)
        service_build = request.get('build', None)
        service_ports = request.get('ports', None)
        service_env = request.get('environment', None)
        
        if service_image is None and service_build is None and service_ports is None and service_env is None:
            return {"success": False, "error": "At least one of image, build, ports, or environment must be provided"}
        
        # Read current compose file
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"success": False, "error": f"Docker Compose file not found: {DOCKER_COMPOSE_PATH}"}
        
        # Parse YAML file
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        # Check if services section exists
        if 'services' not in compose_data:
            return {"success": False, "error": "No services section found in docker-compose.yml"}
        
        # Check if service exists
        if service_name not in compose_data['services']:
            return {"success": False, "error": f"Service {service_name} not found"}
        
        # Update service configuration
        service_config = compose_data['services'][service_name]
        
        if service_image is not None:
            if isinstance(service_image, str) and service_image.strip():
                service_config['image'] = service_image.strip()
            else:
                service_config.pop('image', None)
        
        if service_build is not None:
            if isinstance(service_build, dict):
                build_context = service_build.get('context', '').strip()
                if not build_context:
                    return {"success": False, "error": "Build context is required when build is provided"}
                build_config = {'context': build_context}
                dockerfile = service_build.get('dockerfile', '')
                if isinstance(dockerfile, str) and dockerfile.strip():
                    build_config['dockerfile'] = dockerfile.strip()
                args = service_build.get('args')
                if isinstance(args, dict) and args:
                    build_config['args'] = {k: str(v) for k, v in args.items()}
                target = service_build.get('target')
                if target is not None and str(target).strip():
                    build_config['target'] = str(target).strip()
                service_config['build'] = build_config
            elif isinstance(service_build, str) and service_build.strip():
                service_config['build'] = service_build.strip()
            else:
                service_config.pop('build', None)
        
        if 'image' not in service_config and 'build' not in service_config:
            return {"success": False, "error": "Service must include at least an image or a build context"}
        
        # Update ports if provided
        if service_ports is not None and isinstance(service_ports, list):
            if service_ports:
                ports_list = []
                for port in service_ports:
                    if isinstance(port, dict):
                        port_dict = {
                            'target': int(port.get('target', 0)),
                            'published': int(port.get('published', 0)),
                            'protocol': port.get('protocol', 'tcp')
                        }
                        ports_list.append(port_dict)
                service_config['ports'] = ports_list
            else:
                # Remove ports if empty list provided
                service_config.pop('ports', None)
        
        # Update environment variables if provided
        if service_env is not None and isinstance(service_env, dict):
            if service_env:
                env_dict = {}
                for key, value in service_env.items():
                    if key.strip() and value is not None:
                        env_dict[key.strip()] = str(value).strip()
                service_config['environment'] = env_dict
            else:
                # Remove environment if empty dict provided
                service_config.pop('environment', None)
        
        # Write back to file
        with open(DOCKER_COMPOSE_PATH, 'w') as f:
            yaml.safe_dump(compose_data, f, default_flow_style=False, sort_keys=False)
        
        return {"success": True, "message": f"Service {service_name} updated successfully"}
        
    except Exception as e:
        return {"success": False, "error": f"Error updating service: {str(e)}"}

@app.delete("/api/docker/delete-service/{service_name}")
async def delete_service(service_name: str):
    """Delete a service from Docker Compose file"""
    try:
        # Read current compose file
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"success": False, "error": f"Docker Compose file not found: {DOCKER_COMPOSE_PATH}"}
        
        # Parse YAML file
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        # Check if services section exists
        if 'services' not in compose_data:
            return {"success": False, "error": "No services section found in docker-compose.yml"}
        
        # Check if service exists
        if service_name not in compose_data['services']:
            return {"success": False, "error": f"Service {service_name} not found"}
        
        # Delete the service
        del compose_data['services'][service_name]
        
        # Write back to file with proper YAML formatting
        with open(DOCKER_COMPOSE_PATH, 'w') as f:
            yaml.safe_dump(compose_data, f, default_flow_style=False, sort_keys=False)
        
        return {"success": True, "message": f"Service {service_name} deleted successfully"}
        
    except Exception as e:
        return {"success": False, "error": f"Error deleting service: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
