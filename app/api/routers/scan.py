from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_scan_service, get_price_repo
from app.domain.schemas import ScanRequest, ScanResultsResponse
from app.repository.price_repository import PriceRepository
from app.service.scan_service import ScanService

router = APIRouter(prefix="/scan", tags=["Scan"])


@router.get("/latest-date")
async def get_latest_date(
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)],
):
    """Return the latest trade date that has price data in the DB."""
    latest = await price_repo.get_latest_date()
    if latest is None:
        raise HTTPException(status_code=404, detail="No price data available")
    return {"trade_date": str(latest)}


@router.post("", response_model=ScanResultsResponse)
async def run_scan(
    request: ScanRequest,
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)],
):
    """
    Execute a condition scan on historical data.
    trade_date is optional — defaults to the latest available date in the DB.
    """
    # Resolve trade_date: use latest available if not specified
    if request.trade_date is None:
        latest = await price_repo.get_latest_date()
        if latest is None:
            raise HTTPException(status_code=404, detail="No price data available. Run /admin/trigger-batch first.")
        request = request.model_copy(update={"trade_date": latest})

    try:
        result = await scan_service.run_scan(request, job_type="manual_scan")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    return ScanResultsResponse(
        job={
            "job_id": result["job_id"],
            "trade_date": request.trade_date,
            "status": result["status"],
            "match_count": len(result.get("matches", [])),
        },
        matches=result.get("matches", []),
    )


@router.get("/results/latest", response_model=ScanResultsResponse)
async def get_latest_results(
    scan_service: Annotated[ScanService, Depends(get_scan_service)],
):
    """Return the most recent successful daily batch scan results."""
    data = await scan_service.get_latest_results()
    if data is None:
        raise HTTPException(status_code=404, detail="No completed scan results found")
    return ScanResultsResponse(**data)
