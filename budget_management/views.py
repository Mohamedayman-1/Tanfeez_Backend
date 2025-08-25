from datetime import time
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.db.models import Q, Sum
from django.db.models.functions import Cast
from django.db.models import CharField
from user_management.models import xx_notification
from .models import (
    filter_budget_transfers_all_in_entities,
    xx_BudgetTransfer,
    xx_BudgetTransferAttachment,
    xx_BudgetTransferRejectReason,
)
from account_and_entitys.models import XX_PivotFund, XX_Entity, XX_Account
from adjd_transaction.models import xx_TransactionTransfer
from .serializers import BudgetTransferSerializer
from user_management.permissions import IsAdmin, CanTransferBudget
from budget_transfer.global_function.dashbaord import (
    get_all_dashboard_data, 
    get_saved_dashboard_data, 
    refresh_dashboard_data
)
from public_funtion.update_pivot_fund import update_pivot_fund
import base64
from django.db.models.functions import Cast
from django.db.models import CharField
from collections import defaultdict
from django.db.models import Prefetch
from collections import defaultdict
from decimal import Decimal
import time
import multiprocessing
from itertools import islice
from decimal import Decimal
import multiprocessing
from collections import defaultdict
from decimal import Decimal
import time
from itertools import islice
from django.db import connection
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated


class TransferPagination(PageNumberPagination):
    """Pagination class for budget transfers"""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

class CreateBudgetTransferView(APIView):
    """Create budget transfers"""

    permission_classes = [IsAuthenticated]

    def post(self, request):

        if not request.data.get("transaction_date") or not request.data.get("notes"):
            return Response(
                {
                    "message": "Transaction date and notes are required fields.",
                    "errors": {
                        "transaction_date": (
                            "This field is required."
                            if not request.data.get("transaction_date")
                            else None
                        ),
                        "notes": (
                            "This field is required."
                            if not request.data.get("notes")
                            else None
                        ),
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer_type = request.data.get("type").upper()

        if transfer_type in ["FAR", "AFR", "FAD"]:
            prefix = f"{transfer_type}-"
        else:

            prefix = "FAR-"
            

        last_transfer = (
                xx_BudgetTransfer.objects
                .filter(code__startswith=prefix)
                .order_by("-code")
                .first()
            )

        if last_transfer and last_transfer.code:
            try:
                last_num = int(last_transfer.code.replace(prefix, ""))
                new_num = last_num + 1
            except (ValueError, AttributeError):

                new_num = 1
        else:

            new_num = 1

        new_code = f"{prefix}{new_num:04d}"

        serializer = BudgetTransferSerializer(data=request.data)

        if serializer.is_valid():

            transfer = serializer.save(
                requested_by=request.user.username,
                user_id=request.user.id,
                status="pending",
                request_date=timezone.now(),
                code=new_code,
            )
            Notification_object = xx_notification.objects.create(
                user_id=request.user.id,
                message=f"New budget transfer request created with code {new_code}",
            )
            Notification_object.save()
            return Response(
                {
                    "message": "Budget transfer request created successfully.",
                    "data": BudgetTransferSerializer(transfer).data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ListBudgetTransferView(APIView):
    """List budget transfers with pagination"""

    permission_classes = [IsAuthenticated]
    pagination_class = TransferPagination

    def post(self, request):
        code = request.data.get("code", None)
        date = request.data.get("date", None)
        start_date = request.data.get("start_date", None)
        end_date = request.data.get("end_date", None)
        search = request.data.get("search")

        # Simplify the query to avoid Oracle NCLOB issues
        if request.user.role == "admin":
            transfers = xx_BudgetTransfer.objects.all()
        else:
            transfers = xx_BudgetTransfer.objects.filter(user_id=request.user.id)

       
        print(transfers.count())
        # Skip complex entity filtering for now to avoid NCLOB issues
        # TODO: Implement entity filtering without complex annotations
        
        if request.user.abilities.count() > 0:
            transfers = filter_budget_transfers_all_in_entities(transfers, request.user, 'edit')
        
        print(transfers.count())

        if code:
            transfers = transfers.filter(code__icontains=code)
        print(transfers.count())
        # Use only safe fields for ordering to avoid Oracle NCLOB issues
        transfers = transfers.order_by("-transaction_id")
        
        # Convert to list to avoid lazy evaluation issues with Oracle
        # Exclude TextField columns that become NCLOB in Oracle
        transfer_list = list(transfers.values(
            'transaction_id', 'transaction_date', 'amount', 'status', 
            'requested_by', 'user_id', 'request_date', 'code', 
            'gl_posting_status', 'approvel_1', 'approvel_2', 'approvel_3', 'approvel_4',
            'approvel_1_date', 'approvel_2_date', 'approvel_3_date', 'approvel_4_date',
            'status_level', 'attachment', 'fy', 'group_id', 'interface_id',
            'reject_group_id', 'reject_interface_id', 'approve_group_id', 'approve_interface_id',
            'report', 'type', 'notes'
            # Excluding 'notes' field as it's TextField/NCLOB in Oracle
        ))
        
        # Manual pagination to avoid Oracle issues
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        
        paginated_data = transfer_list[start_idx:end_idx]
        
        return Response({
            'results': paginated_data,
            'count': len(transfer_list),
            'next': f"?page={page + 1}&page_size={page_size}" if end_idx < len(transfer_list) else None,
            'previous': f"?page={page - 1}&page_size={page_size}" if page > 1 else None
        })

class ListBudgetTransfer_approvels_View(APIView):
    """List budget transfers with pagination"""

    permission_classes = [IsAuthenticated]
    pagination_class = TransferPagination

    def get(self, request):
        code = request.query_params.get("code", None)
        date = request.data.get("date", None)
        start_date = request.data.get("start_date", None)
        end_date = request.data.get("end_date", None)
        if code is None:
            code = "FAR"
        status_level_val = (
            request.user.user_level.level_order
            if request.user.user_level.level_order
            else 0
        )
        transfers = xx_BudgetTransfer.objects.filter(
            status_level=status_level_val, code__startswith=code,status= "pending"
        )
        
        if request.user.abilities.count() > 0:
            transfers = filter_budget_transfers_all_in_entities(transfers, request.user, 'approve')
        
        if code:
            transfers = transfers.filter(code__icontains=code)



        transfers = transfers.order_by("-request_date")
        paginator = self.pagination_class()
        paginated_transfers = paginator.paginate_queryset(transfers, request)
        serializer = BudgetTransferSerializer(paginated_transfers, many=True)

        # Create a list of dictionaries with just the fields we want
        filtered_data = []
        for item in serializer.data:
            filtered_item = {
                "transaction_id": item.get("transaction_id"),
                "amount": item.get("amount"),
                "status": item.get("status"),
                "status_level": item.get("status_level"),
                "requested_by": item.get("requested_by"),
                "request_date": item.get("request_date"),
                "code": item.get("code"),
                "transaction_date": item.get("transaction_date"),
            }
            filtered_data.append(filtered_item)

        return paginator.get_paginated_response(filtered_data)

class ApproveBudgetTransferView(APIView):
    """Approve or reject budget transfer requests (admin only)"""

    permission_classes = [IsAuthenticated, IsAdmin]

    def put(self, request, transfer_id):
        try:
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)

            if transfer.status != "pending":
                return Response(
                    {"message": f"This transfer has already been {transfer.status}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            action = request.data.get("action")

            if action not in ["approve", "reject"]:
                return Response(
                    {"message": 'Invalid action. Use "approve" or "reject".'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            transfer.status = "approved" if action == "approve" else "rejected"

            current_level = transfer.status_level or 0
            next_level = current_level + 1

            if next_level <= 4:
                setattr(transfer, f"approvel_{next_level}", request.user.username)
                setattr(transfer, f"approvel_{next_level}_date", timezone.now())
                transfer.status_level = next_level

            transfer.save()

            return Response(
                {
                    "message": f"Budget transfer {transfer.status}.",
                    "data": BudgetTransferSerializer(transfer).data,
                }
            )

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."}, status=status.HTTP_404_NOT_FOUND
            )

class GetBudgetTransferView(APIView):
    """Get a specific budget transfer by ID"""

    permission_classes = [IsAuthenticated]

    def get(self, request, transfer_id):
        try:
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)

            # Check permissions: admin can see all, users can only see their own
            # if request.user.role != 'admin' and transfer.user_id != request.user.id:
            #     return Response(
            #         {'message': 'You do not have permission to view this transfer.'},
            #         status=status.HTTP_403_FORBIDDEN
            #     )
            # serializer = BudgetTransferSerializer(transfer)
            # return Response(serializer.data)
            data = {
                "transaction_id": transfer.transaction_id,
                "amount": transfer.amount,
                "status": transfer.status,
                "requested_by": transfer.requested_by,
                "description": transfer.notes,
            }

            return Response(data)

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."}, status=status.HTTP_404_NOT_FOUND
            )

class UpdateBudgetTransferView(APIView):
    """Update a budget transfer"""

    permission_classes = [IsAuthenticated]

    def put(self, request, transfer_id):

        try:

            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)
             # Get transaction_id from the request
            transaction_id = request.data.get("transaction")
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transaction_id)

            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot upload files for transfer with status "{transfer.status}". Only pending transfers can have files uploaded.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not request.user.role == "admin" and transfer.user_id != request.user.id:

                return Response(
                    {"message": "You do not have permission to update this transfer."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot update transfer with status "{transfer.status}". Only pending transfers can be updated.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = BudgetTransferSerializer(
                transfer, data=request.data, partial=True
            )

            if serializer.is_valid():

                allowed_fields = [
                    "notes",
                    "description_x",
                    "amount",
                    "transaction_date",
                ]

                update_data = {}
                for field in allowed_fields:
                    if field in request.data:
                        update_data[field] = request.data[field]

                if not update_data:
                    return Response(
                        {"message": "No valid fields to update."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                for key, value in update_data.items():
                    setattr(transfer, key, value)

                transfer.save()

                return Response(
                    {
                        "message": "Budget transfer updated successfully.",
                        "data": BudgetTransferSerializer(transfer).data,
                    }
                )

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."}, status=status.HTTP_404_NOT_FOUND
            )

class DeleteBudgetTransferView(APIView):
    """Delete a specific budget transfer by ID"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, transfer_id):
        try:
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)

            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot delete transfer with status "{transfer.status}". Only pending transfers can be deleted.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if request.user.role != "admin" and transfer.user_id != request.user.id:
                return Response(
                    {"message": "You do not have permission to delete this transfer."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            transfer_code = transfer.code
            if transfer.adjd_transfers.exists():
                transfer.adjd_transfers.all().delete()
            transfer.delete()


            return Response(
                {"message": f"Budget transfer {transfer_code} deleted successfully."},
                status=status.HTTP_200_OK,
            )

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {"message": "Transfer not found."}, status=status.HTTP_404_NOT_FOUND
            )

class Adjdtranscationtransferapprovel_reject(APIView):
    """Submit ADJD transaction transfers for approval"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if we received valid data
        if not request.data:
            return Response(
                {
                    "error": "Empty data provided",
                    "message": "Please provide at least one transaction ID",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Convert single item to list for consistent handling
        items_to_process = []
        if isinstance(request.data, list):
            items_to_process = request.data
        else:
            # Handle single transaction case
            items_to_process = [request.data]
        results = []
        # Process each transaction
        for item in items_to_process:
            transaction_id = item.get("transaction_id")[0]
            decide = item.get("decide")[0]
            if item.get("reason") is not None:
                reson = item.get("reason")[0]
            # Validate required fields
            if not transaction_id:
                return Response(
                    {
                        "error": "transaction id is required",
                        "message": "Please provide transaction id",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if decide not in [2, 3]:
                return Response(
                    {
                        "error": "Invalid decision value",
                        "message": "Decision value must be 2 (approve) or 3 (reject)",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if decide == 3 and not reson:
                return Response(
                    {
                        "error": "Reason is required for rejection",
                        "message": "Please provide a reason for rejection",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                # Get the transfer record - use get() for single record
                trasncation = xx_BudgetTransfer.objects.get(
                    transaction_id=transaction_id
                )
                # Get the transfer type code
                code = trasncation.code.split("-")[0]
                # Handle approval flow based on transfer type
                if code == "FAR" or code == "AFR":
                    max_level = 4
                else:
                    max_level = 3
                # Update approval based on decision
                if decide == 2 and trasncation.status_level <= max_level:  # Approve
                    level = trasncation.status_level
                    # Set the appropriate approval fields
                    if level == 2:
                        trasncation.approvel_2 = request.user.username
                        trasncation.approvel_2_date = timezone.now()
                    elif level == 3:
                        trasncation.approvel_3 = request.user.username
                        trasncation.approvel_3_date = timezone.now()
                    elif level == 4:
                        trasncation.approvel_4 = request.user.username
                        trasncation.approvel_4_date = timezone.now()
                    if trasncation.status_level == max_level:
                        trasncation.status = "approved"
                    trasncation.status_level += 1
                elif decide == 3:  # Reject
                    # Record who rejected it at the current level
                    level = trasncation.status_level
                    if level == 2:
                        trasncation.approvel_2 = request.user.username
                        trasncation.approvel_2_date = timezone.now()
                    elif level == 3:
                        trasncation.approvel_3 = request.user.username
                        trasncation.approvel_3_date = timezone.now()
                    elif level == 4:
                        trasncation.approvel_4 = request.user.username
                        trasncation.approvel_4_date = timezone.now()
                    trasncation.status_level = -1
                    Reson_object = xx_BudgetTransferRejectReason.objects.create(
                        Transcation_id=trasncation,
                        reason_text=reson,
                        reject_by=request.user.username,
                    )
                    Reson_object.save()
                    trasncation.status = "rejected"
                # Save changes to the transfer
                trasncation.save()
                # Update pivot fund if final approval or rejection
                pivot_updates = []
                if (
                    max_level == trasncation.status_level and decide == 2
                ) or decide == 3:
                    trasfers = xx_TransactionTransfer.objects.filter(
                        transaction_id=transaction_id
                    )
                    for transfer in trasfers:
                        try:
                            # Extract the necessary data
                            item_cost_center = transfer.cost_center_code
                            item_account_code = transfer.account_code
                            from_center = transfer.from_center or 0
                            to_center = transfer.to_center or 0
                            # Update the pivot fund
                            update_result = update_pivot_fund(
                                item_cost_center,
                                item_account_code,
                                from_center,
                                to_center,
                                decide,
                            )
                            if update_result:
                                pivot_updates.append(update_result)
                        except Exception as e:
                            return Response(
                                {
                                    "error": "Error updating pivot fund",
                                    "message": str(e),
                                },
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            )
                        # Add the result for this transaction
                        results.append(
                            {
                                "transaction_id": transaction_id,
                                "status": "approved" if decide == 2 else "rejected",
                                "status_level": trasncation.status_level,
                                "pivot_updates": pivot_updates,
                            }
                        )
            except xx_BudgetTransfer.DoesNotExist:
                results.append(
                    {
                        "transaction_id": transaction_id,
                        "status": "error",
                        "message": f"Budget transfer not found",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "transaction_id": transaction_id,
                        "status": "error",
                        "message": str(e),
                    }
                )

        # Return all results
        return Response(
            {"message": "Transfers processed", "results": results},
            status=status.HTTP_200_OK,
        )

class BudgetTransferFileUploadView(APIView):
    """Upload files for a budget transfer and store as BLOBs"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Check if the transfer exists
            transaction_id = request.data.get("transaction_id")
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transaction_id)
            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot upload files for transfer with status "{transfer.status}". Only pending transfers can have files uploaded.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if any files were provided
            if not request.FILES:
                return Response(
                    {
                        "error": "No files provided",
                        "message": "Please upload at least one file",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Process each uploaded file
            uploaded_files = []
            for file_key, uploaded_file in request.FILES.items():
                # Read the file data
                file_data = uploaded_file.read()

                # Create the attachment record
                attachment = xx_BudgetTransferAttachment.objects.create(
                    budget_transfer=transfer,
                    file_name=uploaded_file.name,
                    file_type=uploaded_file.content_type,
                    file_size=len(file_data),
                    file_data=file_data,
                )

                uploaded_files.append(
                    {
                        "attachment_id": attachment.attachment_id,
                        "file_name": attachment.file_name,
                        "file_type": attachment.file_type,
                        "file_size": attachment.file_size,
                        "upload_date": attachment.upload_date,
                    }
                )

            # Update the attachment flag on the budget transfer
            transfer.attachment = "Yes"
            transfer.save()

            return Response(
                {
                    "message": f"{len(uploaded_files)} files uploaded successfully",
                    "files": uploaded_files,
                },
                status=status.HTTP_201_CREATED,
            )

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {
                    "error": "Budget transfer not found",
                    "message": f"No budget transfer found with ID: {transaction_id}",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

class DeleteBudgetTransferAttachmentView(APIView):
    """Delete a specific file attachment from a budget transfer"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, transfer_id, attachment_id):
        try:
            # First, check if the budget transfer exists
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)
            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot upload files for transfer with status "{transfer.status}". Only pending transfers can have files uploaded.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if user has permission to modify this transfer
            if not request.user.role == "admin" and transfer.user_id != request.user.id:
                return Response(
                    {
                        "message": "You do not have permission to modify attachments for this transfer."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if transfer is in editable state
            if transfer.status != "pending":
                return Response(
                    {
                        "message": f'Cannot modify attachments for transfer with status "{transfer.status}". Only pending transfers can be modified.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find the specific attachment
            try:
                attachment = xx_BudgetTransferAttachment.objects.get(
                    attachment_id=attachment_id, budget_transfer=transfer
                )

                # Keep attachment details for response
                attachment_details = {
                    "attachment_id": attachment.attachment_id,
                    "file_name": attachment.file_name,
                }

                # Delete the attachment
                attachment.delete()

                # Check if this was the last attachment for this transfer
                remaining_attachments = xx_BudgetTransferAttachment.objects.filter(
                    budget_transfer=transfer
                ).exists()
                if not remaining_attachments:
                    transfer.attachment = "No"
                    transfer.save()

                return Response(
                    {
                        "message": f'File "{attachment_details["file_name"]}" deleted successfully',
                        "attachment_id": attachment_details["attachment_id"],
                    },
                    status=status.HTTP_200_OK,
                )

            except xx_BudgetTransferAttachment.DoesNotExist:
                return Response(
                    {
                        "error": "Attachment not found",
                        "message": f"No attachment found with ID {attachment_id} for this transfer",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {
                    "error": "Budget transfer not found",
                    "message": f"No budget transfer found with ID: {transfer_id}",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

class ListBudgetTransferAttachmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:

            transfer_id = request.query_params.get("transaction_id")
            # Retrieve the main budget transfer record
            transfer = xx_BudgetTransfer.objects.get(transaction_id=transfer_id)

            # Fetch related attachments
            attachments = xx_BudgetTransferAttachment.objects.filter(
                budget_transfer=transfer
            )

            # Build a simplified response
            data = []
            for attach in attachments:
                encoded_data = base64.b64encode(attach.file_data).decode("utf-8")
                data.append(
                    {
                        "attachment_id": attach.attachment_id,
                        "file_name": attach.file_name,
                        "file_type": attach.file_type,
                        "file_size": attach.file_size,
                        "file_data": encoded_data,  # base64-encoded
                        "upload_date": attach.upload_date,
                    }
                )

            return Response(
                {"transaction_id": transfer_id, "attachments": data},
                status=status.HTTP_200_OK,
            )
        except xx_BudgetTransfer.DoesNotExist:
            return Response(
                {"error": "Transfer not found"}, status=status.HTTP_404_NOT_FOUND
            )

class list_budget_transfer_reject_reason(APIView):
    """List all budget transfer reject reasons"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            reasons = xx_BudgetTransferRejectReason.objects.filter(
                Transcation_id=request.query_params.get("transaction_id")
            )
            data = []
            for reason in reasons:
                data.append(
                    {
                        "transaction_id": reason.Transcation_id.transaction_id,
                        "reason_text": reason.reason_text,
                        "created_at": reason.reject_date,
                        "rejected by": reason.reject_by,
                    }
                )
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DashboardBudgetTransferView(APIView):
    """Optimized dashboard view for encrypted budget transfers"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Get dashboard type from query params (default to 'smart')
            dashboard_type = request.query_params.get('type', 'smart')
            
            # Check if user wants to force refresh
            force_refresh = request.query_params.get('refresh', 'false').lower() == 'true'
            
            if force_refresh:
                # Only refresh when explicitly requested
                data = refresh_dashboard_data(dashboard_type)
                if data:
                    return Response(data, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {"error": "Failed to refresh dashboard data"}, 
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                # Always try to get existing cached data first
                if dashboard_type == 'all':
                    # Get all dashboard data (both smart and normal)
                    data = get_all_dashboard_data()
                    if data:
                        return Response(data, status=status.HTTP_200_OK)
                    else:
                        # Return empty structure if no data exists yet
                        return Response(
                            {
                                "message": "No dashboard data available yet. Data will be generated in background.",
                                "data": {}
                            }, 
                            status=status.HTTP_200_OK
                        )
                else:
                    # Get specific dashboard type (smart or normal)
                    data = get_saved_dashboard_data(dashboard_type)
                    if data:
                        return Response(data, status=status.HTTP_200_OK)
                    else:
                        # Return message if no cached data exists
                        return Response(
                            {
                                "message": f"No {dashboard_type} dashboard data available yet. Data will be generated in background.",
                                "data": {}
                            }, 
                            status=status.HTTP_200_OK
                        )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



