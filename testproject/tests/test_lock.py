import pytest
from django_db_backups.services.lock import RestoreLock
import time
import os

def test_restore_lock_lifecycle():
    lock = RestoreLock()
    assert not lock.lock_file.exists()
    
    with lock:
        assert lock.lock_file.exists()
        assert lock.lock_file.read_text() == "LOCKED"
            
    assert not lock.lock_file.exists()

def test_restore_lock_prevents_concurrent_access():
    lock1 = RestoreLock()
    lock2 = RestoreLock()
    
    with lock1:
        with pytest.raises(RuntimeError, match="A restore operation is already in progress."):
            with lock2:
                pass

def test_restore_lock_cleans_up_on_exception():
    lock = RestoreLock()
    
    try:
        with lock:
            raise ValueError("Something went wrong")
    except ValueError:
        pass
        
    assert not lock.lock_file.exists()
    
    

def test_restore_lock_timeout_override():
    lock = RestoreLock()
    
    # Create a stale lock file explicitly
    lock.lock_file.write_text("LOCKED")
    
    # Force modification time to be older than timeout (1800 seconds)
    stale_time = time.time() - 2000
    os.utime(lock.lock_file, (stale_time, stale_time))
    
    # This should succeed and overwrite the stale lock instead of raising an error
    with lock:
        assert lock.lock_file.exists()