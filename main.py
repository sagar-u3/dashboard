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


@app.get("/")
async def get_web_interface():
    """Serve the web interface"""
    return FileResponse('static/index.html')

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "dashboard"}

@app.get("/api/gateway/services")
async def get_gateway_services():
    """Get list of all services for gateway routing"""
    try:
        if not os.path.exists(DOCKER_COMPOSE_PATH):
            return {"services": []}
        
        # Parse YAML file
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            compose_data = yaml.safe_load(f)
        
        services = []
        if 'services' in compose_data:
            for service_name, service_config in compose_data['services'].items():
                service_info = {
                    'name': service_name,
                    'description': service_name.replace('_', ' ').title(),
                    'path': f'/{service_name}' if service_name != 'web-server' else '/',
                    'ports': service_config.get('ports', []),
                    'image': service_config.get('image', ''),
                    'build': service_config.get('build', None)
                }
                
                # Add specific routing info
                if service_name == 'web-server':
                    service_info['path'] = '/'
                    service_info['description'] = 'Gateway and Dashboard'
                elif service_name == 'job_application_tracker':
                    service_info['path'] = '/job-app'
                    service_info['description'] = 'Job Application Tracker'
                elif service_name == 'mongodb':
                    service_info['path'] = '/mongo'
                    service_info['description'] = 'MongoDB Database'
                
                services.append(service_info)
        
        return {"services": services}
        
    except Exception as e:
        return {"error": f"Error getting services: {str(e)}", "services": []}

@app.get("/api/gateway/routes")
async def get_gateway_routes():
    """Get routing configuration for nginx"""
    try:
        services_response = await get_gateway_services()
        if 'error' in services_response:
            return {"routes": []}
        
        routes = []
        for service in services_response['services']:
            if service['name'] == 'web-server':
                continue  # Skip the gateway itself
            
            route_config = {
                'service': service['name'],
                'path': service['path'],
                'target': f"http://{service['name']}:3000" if service['name'] == 'job_application_tracker' else f"http://{service['name']}:27017",
                'description': service['description']
            }
            routes.append(route_config)
        
        return {"routes": routes}
        
    except Exception as e:
        return {"error": f"Error getting routes: {str(e)}", "routes": []}

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
            'environment': {},
            'volumes': [],
            'networks': [],
            'restart': service_config.get('restart', ''),
            'container_name': service_config.get('container_name', ''),
            'working_dir': service_config.get('working_dir', '')
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
        
        # Parse volumes
        if 'volumes' in service_config:
            volumes = service_config['volumes']
            if isinstance(volumes, list):
                for volume in volumes:
                    if isinstance(volume, str):
                        # Parse string format like "/host/path:/container/path:rw"
                        parts = volume.split(':')
                        if len(parts) >= 2:
                            volume_dict = {
                                'source': parts[0],
                                'target': parts[1],
                                'type': 'bind' if '/' in parts[0] else 'volume'
                            }
                            if len(parts) > 2:
                                volume_dict['read_only'] = parts[2] == 'ro'
                            service_data['volumes'].append(volume_dict)
                    elif isinstance(volume, dict):
                        volume_dict = {
                            'source': volume.get('source', ''),
                            'target': volume.get('target', ''),
                            'type': volume.get('type', 'bind')
                        }
                        service_data['volumes'].append(volume_dict)
        
        # Parse networks
        if 'networks' in service_config:
            networks = service_config['networks']
            if isinstance(networks, list):
                for network in networks:
                    service_data['networks'].append({'name': network})
            elif isinstance(networks, dict):
                for network_name, network_config in networks.items():
                    network_dict = {'name': network_name}
                    if isinstance(network_config, dict):
                        network_dict.update(network_config)
                    service_data['networks'].append(network_dict)
        
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
        service_volumes = request.get('volumes', [])
        service_networks = request.get('networks', [])
        restart_policy = request.get('restart', '')
        container_name = request.get('container_name', '')
        working_dir = request.get('working_dir', '')
        
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
        
        # Add volumes if provided
        if service_volumes and isinstance(service_volumes, list):
            volumes_list = []
            for volume in service_volumes:
                if isinstance(volume, dict):
                    source = volume.get('source', '').strip()
                    target = volume.get('target', '').strip()
                    volume_type = volume.get('type', 'bind')
                    
                    if source and target:
                        if volume_type == 'bind':
                            volume_str = f"{source}:{target}"
                        else:
                            volume_str = f"{source}:{target}"
                        
                        # Add read-only flag if specified
                        if volume.get('read_only', False):
                            volume_str += ":ro"
                        
                        volumes_list.append(volume_str)
            if volumes_list:
                new_service['volumes'] = volumes_list
        
        # Add networks if provided
        if service_networks and isinstance(service_networks, list):
            networks_dict = {}
            for network in service_networks:
                if isinstance(network, dict):
                    network_name = network.get('name', '').strip()
                    if network_name:
                        network_config = {}
                        if network.get('mode') == 'external':
                            network_config['external'] = True
                        networks_dict[network_name] = network_config if network_config else None
            if networks_dict:
                new_service['networks'] = networks_dict
        
        # Add additional options if provided
        if restart_policy and restart_policy.strip():
            new_service['restart'] = restart_policy.strip()
        
        if container_name and container_name.strip():
            new_service['container_name'] = container_name.strip()
        
        if working_dir and working_dir.strip():
            new_service['working_dir'] = working_dir.strip()
        
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
        service_volumes = request.get('volumes', None)
        service_networks = request.get('networks', None)
        restart_policy = request.get('restart', None)
        container_name = request.get('container_name', None)
        working_dir = request.get('working_dir', None)
        
        if (service_image is None and service_build is None and service_ports is None and 
            service_env is None and service_volumes is None and service_networks is None and
            restart_policy is None and container_name is None and working_dir is None):
            return {"success": False, "error": "At least one field must be provided for update"}
        
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
        
        # Update volumes if provided
        if service_volumes is not None and isinstance(service_volumes, list):
            if service_volumes:
                volumes_list = []
                for volume in service_volumes:
                    if isinstance(volume, dict):
                        source = volume.get('source', '').strip()
                        target = volume.get('target', '').strip()
                        volume_type = volume.get('type', 'bind')
                        
                        if source and target:
                            if volume_type == 'bind':
                                volume_str = f"{source}:{target}"
                            else:
                                volume_str = f"{source}:{target}"
                            
                            # Add read-only flag if specified
                            if volume.get('read_only', False):
                                volume_str += ":ro"
                            
                            volumes_list.append(volume_str)
                service_config['volumes'] = volumes_list
            else:
                # Remove volumes if empty list provided
                service_config.pop('volumes', None)
        
        # Update networks if provided
        if service_networks is not None and isinstance(service_networks, list):
            if service_networks:
                networks_dict = {}
                for network in service_networks:
                    if isinstance(network, dict):
                        network_name = network.get('name', '').strip()
                        if network_name:
                            network_config = {}
                            if network.get('mode') == 'external':
                                network_config['external'] = True
                            networks_dict[network_name] = network_config if network_config else None
                service_config['networks'] = networks_dict
            else:
                # Remove networks if empty list provided
                service_config.pop('networks', None)
        
        # Update additional options if provided
        if restart_policy is not None:
            if restart_policy.strip():
                service_config['restart'] = restart_policy.strip()
            else:
                service_config.pop('restart', None)
        
        if container_name is not None:
            if container_name.strip():
                service_config['container_name'] = container_name.strip()
            else:
                service_config.pop('container_name', None)
        
        if working_dir is not None:
            if working_dir.strip():
                service_config['working_dir'] = working_dir.strip()
            else:
                service_config.pop('working_dir', None)
        
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
