#!/usr/bin/env python3
"""
Model Registry Manager

Manages the model registry stored on FSx Lustre at /fsx/metadata/model-registry.json

Commands:
- list: List all registered models
- add: Add a model to registry
- remove: Remove a model from registry
- update: Update model metadata
- validate: Validate all models exist on FSx
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class ModelRegistryManager:
    """Manages model registry on FSx"""

    def __init__(self, registry_path: str = "/fsx/metadata/model-registry.json"):
        """
        Initialize registry manager

        Args:
            registry_path: Path to model registry JSON file
        """
        self.registry_path = registry_path
        self.registry_dir = os.path.dirname(registry_path)

        # Ensure registry directory exists
        if not os.path.exists(self.registry_dir):
            print(f"Creating registry directory: {self.registry_dir}")
            os.makedirs(self.registry_dir, exist_ok=True)

        # Load or create registry
        self.registry = self._load_registry()

    def _load_registry(self) -> Dict:
        """
        Load registry from file

        Returns:
            Registry dict
        """
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading registry: {e}")
                return {}
        else:
            print(f"Registry not found, creating new: {self.registry_path}")
            return {}

    def _save_registry(self):
        """Save registry to file"""
        try:
            with open(self.registry_path, 'w') as f:
                json.dump(self.registry, f, indent=2, sort_keys=True)
            print(f"✓ Registry saved to: {self.registry_path}")
        except Exception as e:
            print(f"Error saving registry: {e}")
            sys.exit(1)

    def list_models(self) -> List[Dict]:
        """
        List all registered models

        Returns:
            List of model entries
        """
        return [
            {
                'model_pool': pool,
                **info
            }
            for pool, info in self.registry.items()
        ]

    def add_model(
        self,
        model_pool: str,
        name: str,
        path: str,
        size_gb: float,
        preload: bool = False,
        s3_source: Optional[str] = None
    ) -> bool:
        """
        Add model to registry

        Args:
            model_pool: Model pool ID
            name: Human-readable name
            path: FSx path to model
            size_gb: Model size in GB
            preload: Preload on startup
            s3_source: S3 source path

        Returns:
            True if added successfully
        """
        if model_pool in self.registry:
            print(f"Warning: Model {model_pool} already exists in registry")
            print("Use 'update' command to modify existing model")
            return False

        # Validate model path exists
        if not os.path.exists(path):
            print(f"Error: Model path not found: {path}")
            return False

        # Validate required files
        required_files = ['config.json']
        for file in required_files:
            file_path = os.path.join(path, file)
            if not os.path.exists(file_path):
                print(f"Error: Required file not found: {file_path}")
                return False

        # Add to registry
        self.registry[model_pool] = {
            'name': name,
            'path': path,
            'size_gb': size_gb,
            'preload': preload,
            's3_source': s3_source,
            'added_at': datetime.utcnow().isoformat() + 'Z',
            'added_by': os.environ.get('USER', 'unknown')
        }

        self._save_registry()

        print(f"✓ Added model: {model_pool}")
        return True

    def remove_model(self, model_pool: str) -> bool:
        """
        Remove model from registry

        Args:
            model_pool: Model pool ID

        Returns:
            True if removed successfully
        """
        if model_pool not in self.registry:
            print(f"Error: Model not found: {model_pool}")
            return False

        del self.registry[model_pool]
        self._save_registry()

        print(f"✓ Removed model: {model_pool}")
        return True

    def update_model(
        self,
        model_pool: str,
        **kwargs
    ) -> bool:
        """
        Update model metadata

        Args:
            model_pool: Model pool ID
            **kwargs: Fields to update

        Returns:
            True if updated successfully
        """
        if model_pool not in self.registry:
            print(f"Error: Model not found: {model_pool}")
            return False

        # Update fields
        for key, value in kwargs.items():
            if value is not None:
                self.registry[model_pool][key] = value

        # Update timestamp
        self.registry[model_pool]['updated_at'] = datetime.utcnow().isoformat() + 'Z'

        self._save_registry()

        print(f"✓ Updated model: {model_pool}")
        return True

    def validate_models(self) -> Dict[str, bool]:
        """
        Validate all models exist on FSx

        Returns:
            Dict mapping model_pool to validation status
        """
        results = {}

        for model_pool, info in self.registry.items():
            path = info['path']

            # Check path exists
            if not os.path.exists(path):
                print(f"✗ {model_pool}: Path not found: {path}")
                results[model_pool] = False
                continue

            # Check required files
            required_files = ['config.json']
            all_files_exist = True

            for file in required_files:
                file_path = os.path.join(path, file)
                if not os.path.exists(file_path):
                    print(f"✗ {model_pool}: Missing file: {file}")
                    all_files_exist = False

            results[model_pool] = all_files_exist

            if all_files_exist:
                print(f"✓ {model_pool}: Valid")

        return results

    def get_model(self, model_pool: str) -> Optional[Dict]:
        """
        Get model info

        Args:
            model_pool: Model pool ID

        Returns:
            Model info or None
        """
        return self.registry.get(model_pool)

    def get_stats(self) -> Dict:
        """
        Get registry statistics

        Returns:
            Stats dict
        """
        total_models = len(self.registry)
        total_size_gb = sum(info.get('size_gb', 0) for info in self.registry.values())
        preload_count = sum(1 for info in self.registry.values() if info.get('preload', False))

        return {
            'total_models': total_models,
            'total_size_gb': round(total_size_gb, 2),
            'preload_count': preload_count,
            'registry_path': self.registry_path
        }


def main():
    parser = argparse.ArgumentParser(
        description="Manage model registry on FSx Lustre"
    )

    parser.add_argument(
        '--registry-path',
        default='/fsx/metadata/model-registry.json',
        help='Path to model registry file'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # List command
    subparsers.add_parser('list', help='List all models')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a model')
    add_parser.add_argument('--model-pool', required=True, help='Model pool ID')
    add_parser.add_argument('--name', required=True, help='Model name')
    add_parser.add_argument('--path', required=True, help='FSx path to model')
    add_parser.add_argument('--size-gb', type=float, required=True, help='Model size in GB')
    add_parser.add_argument('--preload', action='store_true', help='Preload on startup')
    add_parser.add_argument('--s3-source', help='S3 source path')

    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a model')
    remove_parser.add_argument('--model-pool', required=True, help='Model pool ID')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update a model')
    update_parser.add_argument('--model-pool', required=True, help='Model pool ID')
    update_parser.add_argument('--name', help='Model name')
    update_parser.add_argument('--preload', type=bool, help='Preload on startup')
    update_parser.add_argument('--s3-source', help='S3 source path')

    # Validate command
    subparsers.add_parser('validate', help='Validate all models')

    # Stats command
    subparsers.add_parser('stats', help='Show registry statistics')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize manager
    manager = ModelRegistryManager(args.registry_path)

    # Execute command
    if args.command == 'list':
        models = manager.list_models()

        if not models:
            print("No models registered")
            return

        print(f"\n{'Model Pool':<15} {'Name':<30} {'Size (GB)':<10} {'Preload':<8} {'Path':<50}")
        print("-" * 120)

        for model in models:
            print(f"{model['model_pool']:<15} {model.get('name', 'N/A'):<30} {model.get('size_gb', 0):<10.2f} {str(model.get('preload', False)):<8} {model.get('path', 'N/A'):<50}")

        print("")
        stats = manager.get_stats()
        print(f"Total: {stats['total_models']} models, {stats['total_size_gb']} GB")

    elif args.command == 'add':
        manager.add_model(
            model_pool=args.model_pool,
            name=args.name,
            path=args.path,
            size_gb=args.size_gb,
            preload=args.preload,
            s3_source=args.s3_source
        )

    elif args.command == 'remove':
        manager.remove_model(args.model_pool)

    elif args.command == 'update':
        updates = {}
        if args.name:
            updates['name'] = args.name
        if args.preload is not None:
            updates['preload'] = args.preload
        if args.s3_source:
            updates['s3_source'] = args.s3_source

        manager.update_model(args.model_pool, **updates)

    elif args.command == 'validate':
        print("\nValidating models...\n")
        results = manager.validate_models()

        print("\nValidation Results:")
        valid_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        print(f"  {valid_count}/{total_count} models are valid")

        if valid_count < total_count:
            sys.exit(1)

    elif args.command == 'stats':
        stats = manager.get_stats()

        print("\nRegistry Statistics:")
        print(f"  Total models: {stats['total_models']}")
        print(f"  Total size: {stats['total_size_gb']} GB")
        print(f"  Preload count: {stats['preload_count']}")
        print(f"  Registry path: {stats['registry_path']}")
        print("")


if __name__ == '__main__':
    main()
